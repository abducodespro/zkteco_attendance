"""
ZKTeco Dashboard page controller.
"""
import frappe


def get_context(context):
    """Inject context into the dashboard Jinja template."""
    context.no_cache = 1
    context.title = "ZKTeco Attendance Dashboard"
