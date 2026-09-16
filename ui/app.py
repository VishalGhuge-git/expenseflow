"""Streamlit front-end for ExpenseFlow: submit an expense, list expenses, and view spending insights."""

import os

import httpx
import pandas as pd
import streamlit as st

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")


def _request(method: str, path: str, **kwargs) -> httpx.Response | None:
    """Call the ExpenseFlow API, showing a friendly message instead of a stack trace on failure."""
    try:
        return httpx.request(method, f"{API_BASE}{path}", timeout=10.0, **kwargs)
    except httpx.ConnectError:
        st.error(f"Could not connect to the ExpenseFlow API at {API_BASE}. Is it running?")
    except httpx.HTTPError as exc:
        st.error(f"Request to the API failed: {exc}")
    return None


st.set_page_config(page_title="ExpenseFlow", page_icon="\U0001F4B3")
st.title("ExpenseFlow")

st.header("Submit an expense")
with st.form("submit_expense", clear_on_submit=True):
    submitted_by = st.text_input("Submitted by")
    amount = st.number_input("Amount", min_value=0.01, step=0.01, format="%.2f")
    currency = st.text_input("Currency (ISO 4217, e.g. INR)", value="INR")
    category = st.text_input("Category")
    description = st.text_input("Description")
    submitted = st.form_submit_button("Submit expense")

if submitted:
    if not submitted_by or not category or not description:
        st.warning("Submitted by, category, and description are required.")
    else:
        payload = {
            "submitted_by": submitted_by,
            "amount_minor": round(amount * 100),
            "currency": currency.strip().upper(),
            "category": category,
            "description": description,
        }
        response = _request("POST", "/expenses", json=payload)
        if response is not None:
            if response.status_code == 201:
                st.success(f"Expense #{response.json()['id']} submitted.")
            else:
                st.error(f"API error ({response.status_code}): {response.text}")

STATUS_COLORS = {
    "approved": "background-color: #d4edda; color: #155724",
    "rejected": "background-color: #f8d7da; color: #721c24",
    "pending": "background-color: #fff3cd; color: #856404",
}


def _style_status(value: str) -> str:
    """Return a CSS style string that color-codes a status cell."""
    return STATUS_COLORS.get(value, "")


st.header("Expenses")
expenses: list[dict] = []
expenses_response = _request("GET", "/expenses")
if expenses_response is not None:
    if expenses_response.status_code == 200:
        expenses = expenses_response.json()
        if expenses:
            expenses_df = pd.DataFrame(expenses)
            styled_expenses = expenses_df.style.map(_style_status, subset=["status"])
            st.dataframe(styled_expenses, use_container_width=True)
        else:
            st.info("No expenses yet.")
    else:
        st.error(f"API error ({expenses_response.status_code}): {expenses_response.text}")

st.header("Approve / reject an expense")
pending_expenses = [expense for expense in expenses if expense["status"] == "pending"]
if pending_expenses:
    options = {
        f"#{expense['id']} - {expense['description']} ({expense['amount_base_minor']} paise)": expense["id"]
        for expense in pending_expenses
    }
    selected_label = st.selectbox("Pending expense", list(options.keys()))
    selected_id = options[selected_label]
    decided_by = st.text_input("Decided by")
    reason = st.text_input("Rejection reason (optional, used only on reject)")

    approve_col, reject_col = st.columns(2)
    with approve_col:
        if st.button("Approve", use_container_width=True):
            if not decided_by:
                st.warning("Decided by is required.")
            else:
                decision_response = _request(
                    "POST", f"/expenses/{selected_id}/approve", json={"decided_by": decided_by}
                )
                if decision_response is not None:
                    if decision_response.status_code == 200:
                        st.success(f"Expense #{selected_id} approved.")
                        st.rerun()
                    else:
                        st.error(f"API error ({decision_response.status_code}): {decision_response.text}")
    with reject_col:
        if st.button("Reject", use_container_width=True):
            if not decided_by:
                st.warning("Decided by is required.")
            else:
                decision_response = _request(
                    "POST",
                    f"/expenses/{selected_id}/reject",
                    json={"decided_by": decided_by, "reason": reason or None},
                )
                if decision_response is not None:
                    if decision_response.status_code == 200:
                        st.success(f"Expense #{selected_id} rejected.")
                        st.rerun()
                    else:
                        st.error(f"API error ({decision_response.status_code}): {decision_response.text}")
else:
    st.info("No pending expenses to decide on.")

st.header("Insights")
if st.button("Generate insights"):
    insights_response = _request("GET", "/reports/insights")
    if insights_response is not None:
        if insights_response.status_code == 200:
            st.markdown(insights_response.json()["insight"])
        else:
            st.error(f"API error ({insights_response.status_code}): {insights_response.text}")
