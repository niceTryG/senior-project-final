from flask_wtf import FlaskForm
from wtforms import IntegerField, TextAreaField, SelectField, FieldList, FormField, FloatField, HiddenField, DateField
from wtforms.validators import DataRequired, NumberRange, Optional
from datetime import date

# --- CuttingOrder forms (Phase 2) ---
class CuttingOrderMaterialForm(FlaskForm):
    material_id = HiddenField("Material ID", validators=[DataRequired()])
    used_amount = FloatField("Used Amount", validators=[Optional(), NumberRange(min=0)])

class CuttingOrderForm(FlaskForm):
    product_id = SelectField("Product", coerce=int, validators=[DataRequired()])
    cut_date = DateField("Cut Date", format="%Y-%m-%d", validators=[DataRequired()], default=date.today)
    sets_cut = IntegerField("Pieces Cut", validators=[DataRequired(), NumberRange(min=1)])
    notes = TextAreaField("Notes")
    materials = FieldList(FormField(CuttingOrderMaterialForm), min_entries=1)
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, SelectField, DateField
from wtforms.validators import DataRequired, Length, EqualTo, Optional


ONBOARDING_PHONE_COUNTRY_CHOICES = [
    ("+998", "UZB +998"),
    ("+7", "KAZ/RUS +7"),
    ("+996", "KGZ +996"),
    ("+992", "TJK +992"),
    ("+993", "TKM +993"),
    ("+994", "AZE +994"),
    ("+90", "TUR +90"),
    ("+971", "UAE +971"),
]


class ProfileUpdateForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            Optional(),
            Length(min=3, max=64),
        ],
    )
    full_name = StringField(
        "Full name",
        validators=[
            Optional(),
            Length(max=128),
        ],
    )
    phone = StringField(
        "Phone",
        validators=[
            Optional(),
            Length(max=64),
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


class SecurityWallPasswordForm(FlaskForm):
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
    submit_security_password = SubmitField("Unlock workspace")


class TelegramLinkCodeForm(FlaskForm):
    submit_telegram_code = SubmitField("Generate Telegram code")


class WorkspaceProfileForm(FlaskForm):
    name = StringField(
        "Business name",
        validators=[
            DataRequired(),
            Length(min=2, max=128),
        ],
    )
    owner_name = StringField(
        "Owner name",
        validators=[
            Optional(),
            Length(max=128),
        ],
    )
    location = StringField(
        "Location",
        validators=[
            Optional(),
            Length(max=128),
        ],
    )
    phone = StringField(
        "Phone",
        validators=[
            Optional(),
            Length(max=64),
        ],
    )
    note = TextAreaField(
        "Note",
        validators=[
            Optional(),
            Length(max=255),
        ],
    )
    submit_workspace = SubmitField("Save workspace")


class WorkspaceTeamMemberForm(FlaskForm):
    full_name = StringField(
        "Full name",
        validators=[
            DataRequired(),
            Length(max=128),
        ],
    )
    phone = StringField(
        "Phone",
        validators=[
            Optional(),
            Length(max=64),
        ],
    )
    username = StringField(
        "Username",
        validators=[
            Optional(),
            Length(min=3, max=64),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=6, max=128),
        ],
    )
    role = SelectField(
        "Role",
        choices=[
            ("manager", "Manager"),
            ("viewer", "Viewer"),
            ("shop", "Shop"),
            ("accountant", "Accountant"),
        ],
        validators=[DataRequired()],
    )
    shop_id = SelectField(
        "Shop",
        coerce=int,
        choices=[(0, "No shop")],
        validators=[Optional()],
    )
    submit_member = SubmitField("Add team member")


class WorkspaceOwnershipTransferForm(FlaskForm):
    new_owner_id = SelectField(
        "New owner",
        coerce=int,
        choices=[(0, "Select a team member")],
        validators=[DataRequired()],
    )
    current_password = PasswordField(
        "Current password",
        validators=[DataRequired()],
    )
    submit_transfer = SubmitField("Transfer ownership")


class OperationalTaskForm(FlaskForm):
    title = StringField(
        "Title",
        validators=[
            DataRequired(),
            Length(min=3, max=160),
        ],
    )
    description = TextAreaField(
        "Description",
        validators=[
            Optional(),
            Length(max=255),
        ],
    )
    priority = SelectField(
        "Priority",
        choices=[
            ("urgent", "Urgent"),
            ("high", "High"),
            ("medium", "Medium"),
            ("low", "Low"),
        ],
        validators=[DataRequired()],
    )
    assigned_user_id = SelectField(
        "Assign to",
        coerce=int,
        choices=[(0, "No specific assignee")],
        validators=[Optional()],
    )
    target_role = SelectField(
        "Role target",
        choices=[
            ("", "No role target"),
            ("admin", "Admin"),
            ("manager", "Manager"),
            ("accountant", "Accountant"),
            ("viewer", "Viewer"),
            ("shop", "Shop"),
        ],
        validators=[Optional()],
    )
    due_date = DateField(
        "Due date",
        format="%Y-%m-%d",
        validators=[Optional()],
    )
    action_url = StringField(
        "Action link",
        validators=[
            Optional(),
            Length(max=255),
        ],
    )
    submit_task = SubmitField("Create task")


class OnboardingOwnerForm(FlaskForm):
    full_name = StringField(
        "Full name",
        validators=[
            DataRequired(),
            Length(min=2, max=128),
        ],
    )
    phone_country_code = SelectField(
        "Country code",
        choices=ONBOARDING_PHONE_COUNTRY_CHOICES,
        default="+998",
        validators=[DataRequired()],
    )
    phone_number = StringField(
        "Phone number",
        validators=[
            DataRequired(),
            Length(max=64),
        ],
    )
    username = StringField(
        "Username",
        validators=[
            Optional(),
            Length(min=3, max=64),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=6, max=128),
        ],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[
            DataRequired(),
            EqualTo("password", message="Passwords must match."),
        ],
    )
    language = SelectField(
        "Language",
        choices=[
            ("en", "English"),
            ("ru", "Русский"),
            ("uz", "O'zbek"),
        ],
        validators=[DataRequired()],
    )
    submit_owner = SubmitField("Continue to workspace")


class OnboardingVerifyForm(FlaskForm):
    submit_verify = SubmitField("Continue to workspace")


class OnboardingWorkspaceForm(FlaskForm):
    name = StringField(
        "Business name",
        validators=[
            DataRequired(),
            Length(min=2, max=128),
        ],
    )
    owner_name = StringField(
        "Owner name",
        validators=[
            Optional(),
            Length(max=128),
        ],
    )
    location = StringField(
        "Location",
        validators=[
            Optional(),
            Length(max=128),
        ],
    )
    phone = StringField(
        "Phone",
        validators=[
            Optional(),
            Length(max=64),
        ],
    )
    note = TextAreaField(
        "Note",
        validators=[
            Optional(),
            Length(max=255),
        ],
    )
    submit_workspace_setup = SubmitField("Continue to first shop")


class OnboardingShopForm(FlaskForm):
    name = StringField(
        "Shop name",
        validators=[
            Optional(),
            Length(max=128),
        ],
    )
    location = StringField(
        "Location",
        validators=[
            Optional(),
            Length(max=128),
        ],
    )
    note = TextAreaField(
        "Note",
        validators=[
            Optional(),
            Length(max=255),
        ],
    )
    submit_shop = SubmitField("Continue to team")


class OnboardingTeamForm(FlaskForm):
    full_name = StringField(
        "Full name",
        validators=[
            Optional(),
            Length(max=128),
        ],
    )
    phone = StringField(
        "Phone",
        validators=[
            Optional(),
            Length(max=64),
        ],
    )
    username = StringField(
        "Username",
        validators=[
            Optional(),
            Length(min=3, max=64),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            Optional(),
            Length(min=6, max=128),
        ],
    )
    role = SelectField(
        "Role",
        choices=[
            ("manager", "Manager"),
            ("viewer", "Viewer"),
            ("shop", "Shop"),
            ("accountant", "Accountant"),
        ],
        validators=[Optional()],
    )
    shop_target = SelectField(
        "Linked shop",
        choices=[("none", "No shop")],
        validators=[Optional()],
    )
    submit_team = SubmitField("Review workspace")


class OnboardingLaunchForm(FlaskForm):
    submit_launch = SubmitField("Create workspace and open dashboard")
