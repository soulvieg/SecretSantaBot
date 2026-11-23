from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    discord_id: Mapped[str | None] = mapped_column(sa.String(32), unique=True, nullable=True)
    telegram_id: Mapped[str | None] = mapped_column(sa.String(64), unique=True, nullable=True)
    steam_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    steam_whishlist_url: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    __table_args__ = (
        sa.CheckConstraint(
            "discord_id IS NOT NULL OR telegram_id IS NOT NULL",
            name="check_users_identity"
        ),
    )


class Circle(Base):
    __tablename__ = "circles"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    owner_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    discord_server_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    announce_channel_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, server_default="draft")
    card_msg_id: Mapped[int | None] = mapped_column(sa.BigInteger, unique=True, nullable=True)
    budget: Mapped[int | None] = mapped_column(sa.Integer, nullable=True) # budget and prices are in cents
    currency: Mapped[str] = mapped_column(sa.String(4), nullable=False, server_default="EUR")
    signup_deadline: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    avoid_repeat: Mapped[bool] = mapped_column(nullable=False, server_default=sa.false())
    exchange_date: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    current_round: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    created_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now())

    __table_args__ = (
        sa.UniqueConstraint("discord_server_id", "name", name="unique_circles_server_name"),
        sa.CheckConstraint(
            "status IN ('draft', 'open', 'collecting', 'drawn', 'closed')",
            name="check_circles_status"
        ),
    )


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    circle_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("circles.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    withdrawn_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    ready: Mapped[bool] = mapped_column(nullable=False, server_default=sa.false())
    panel_msg_id: Mapped[int | None] = mapped_column(sa.BigInteger, unique=True, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("circle_id", "user_id", name="unique_user_circle"),
    )

class WishlistItem(Base):
    __tablename__ = "wishlist_items"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    participant_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(sa.String(2048), nullable=True)
    price: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(sa.String(1024), nullable=True)
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))


class ContactInfo(Base):
    __tablename__ = "contact_info"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    participant_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("participants.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    # name: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    # surname: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    # alt_name: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    # alt_surname: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    # address1: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    # address2: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    # address3: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    # phone_number: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    # email_address: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    payload: Mapped[str] = mapped_column(sa.String(2048), nullable=False) # Fernet


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    circle_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("circles.id", ondelete="CASCADE"), nullable=False)
    round: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    giver_participant_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False)
    receiver_participant_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False)
    drawn_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


    __table_args__ = (
        sa.UniqueConstraint(
            "circle_id", "round", "giver_participant_id", name="unique_assignment_round_giver"
        ),
        sa.UniqueConstraint(
            "circle_id", "round", "receiver_participant_id", name="unique_assignment_round_receiver"
        ),
        sa.CheckConstraint(
            "giver_participant_id <> receiver_participant_id", name="check_assignment_no_to_self"
        ),
    )


class Shipment(Base):
    __tablename__ = "shipments"

    assignment_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True)
    carrier: Mapped[str] = mapped_column(sa.String(128))
    tracking_number: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    note: Mapped[str | None] = mapped_column(sa.String(1024), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class Exclusion(Base):
    __tablename__ = "exclusions"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    circle_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("circles.id", ondelete="CASCADE"), index=True, nullable=False)
    giver_participant_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    excluded_participant_id: Mapped[int] = mapped_column(sa.Integer, sa.ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint(
            "circle_id", "giver_participant_id", "excluded_participant_id", name="unique_participant_pair"
        ),
        sa.CheckConstraint(
            "giver_participant_id <> excluded_participant_id", name="check_exclusion_no_to_self"
        ),
    )
