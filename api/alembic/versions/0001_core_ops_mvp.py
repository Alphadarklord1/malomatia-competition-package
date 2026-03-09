"""Core ops MVP schema

Revision ID: 0001_core_ops_mvp
Revises: 
Create Date: 2026-03-10 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_core_ops_mvp"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("auth_provider", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until_utc", sa.DateTime(), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mfa_secret", sa.String(), nullable=True),
        sa.Column("last_login_at_utc", sa.DateTime(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "case",
        sa.Column("case_id", sa.String(), primary_key=True),
        sa.Column("request_text_ar", sa.String(), nullable=False),
        sa.Column("request_text_en", sa.String(), nullable=False),
        sa.Column("intent_ar", sa.String(), nullable=False),
        sa.Column("intent_en", sa.String(), nullable=False),
        sa.Column("urgency_ar", sa.String(), nullable=False),
        sa.Column("urgency_en", sa.String(), nullable=False),
        sa.Column("department_ar", sa.String(), nullable=False),
        sa.Column("department_en", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason_ar", sa.String(), nullable=False),
        sa.Column("reason_en", sa.String(), nullable=False),
        sa.Column("detected_keywords_ar", sa.String(), nullable=False),
        sa.Column("detected_keywords_en", sa.String(), nullable=False),
        sa.Column("detected_time_ar", sa.String(), nullable=False),
        sa.Column("detected_time_en", sa.String(), nullable=False),
        sa.Column("policy_rule", sa.String(), nullable=False),
        sa.Column("status_ar", sa.String(), nullable=False),
        sa.Column("status_en", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("assigned_team", sa.String(), nullable=True),
        sa.Column("assigned_user", sa.String(), nullable=True),
        sa.Column("sla_deadline_utc", sa.DateTime(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
        sa.Column("triaged_at_utc", sa.DateTime(), nullable=True),
        sa.Column("assigned_at_utc", sa.DateTime(), nullable=True),
        sa.Column("resolved_at_utc", sa.DateTime(), nullable=True),
        sa.Column("closed_at_utc", sa.DateTime(), nullable=True),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "workflowevent",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=False),
        sa.Column("actor_role", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("from_state", sa.String(), nullable=True),
        sa.Column("to_state", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("timestamp_utc", sa.DateTime(), nullable=False),
        sa.Column("meta_json", sa.String(), nullable=False),
    )
    op.create_table(
        "auditevent",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("details_json", sa.String(), nullable=False),
        sa.Column("prev_hash", sa.String(), nullable=False),
        sa.Column("event_hash", sa.String(), nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "notification",
        sa.Column("notification_id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("ack_by_user", sa.String(), nullable=True),
        sa.Column("ack_at_utc", sa.DateTime(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notification")
    op.drop_table("auditevent")
    op.drop_table("workflowevent")
    op.drop_table("case")
    op.drop_table("user")
