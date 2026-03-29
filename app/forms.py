from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, Optional


class ProfileUpdateForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(min=3, max=64),
        ],
    )
    submit_profile = SubmitField("Save changes")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(
        "Current password",
        validators=[DataRequired()],
    )

    new_password = PasswordField(
        "New password",
        validators=[
            DataRequired(),
            Length(min=6, max=128),
        ],
    )

    confirm_new_password = PasswordField(
        "Confirm new password",
        validators=[
            DataRequired(),
            EqualTo("new_password", message="Passwords must match."),
        ],
    )

    submit_password = SubmitField("Update password")


class TelegramLinkCodeForm(FlaskForm):
    submit_telegram_code = SubmitField("Generate Telegram code")
