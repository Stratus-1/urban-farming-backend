"""Brand-consistent, accessible HTML and plain-text transactional emails."""

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text: str
    html: str

    def to_message(self, recipient: str):
        from app.infrastructure.email import MailMessage

        return MailMessage(to=recipient, subject=self.subject, text=self.text, html=self.html)


GREEN = "#17452b"
INK = "#20352a"
MUTED = "#5d6d62"
PALE = "#f4f6f1"
LINE = "#e5eae2"
LOGO_URL = "https://urbanfarmingofficial.com/icons/icon-192.png"


def _layout(
    *,
    preheader: str,
    title: str,
    body: str,
    action: tuple[str, str] | None = None,
    eyebrow: str | None = None,
) -> str:
    button = ""
    if action:
        label, url = action
        button = (
            '<tr><td style="padding:24px 0 0">'
            '<table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr><td '
            f'bgcolor="{GREEN}" style="background:{GREEN};border-radius:7px">'
            f'<a href="{escape(url, quote=True)}" style="display:inline-block;color:#ffffff;'
            'font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:20px;font-weight:700;'
            'text-decoration:none;padding:14px 22px;border:1px solid '
            f'{GREEN};border-radius:7px">{escape(label)}</a>'
            '</td></tr></table></td></tr>'
            '<tr><td style="padding:12px 0 0;color:#69776d;font-size:12px;line-height:1.6">'
            'If the button does not work, copy and paste this link into your browser:<br>'
            f'<a href="{escape(url, quote=True)}" style="color:{GREEN};word-break:break-all">'
            f'{escape(url)}</a></td></tr>'
        )
    eyebrow_markup = (
        '<div style="margin:22px 0 0"><span style="display:inline-block;padding:6px 10px;'
        'border-radius:20px;background:#edf4ea;color:#28573a;font-size:10px;line-height:12px;'
        'font-weight:700;letter-spacing:1px">'
        f'{escape(eyebrow.upper())}</span></div>'
        if eyebrow
        else ""
    )
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>{escape(title)}</title></head>
<body bgcolor="{PALE}" style="margin:0;padding:0;background:{PALE};font-family:Arial,Helvetica,sans-serif;color:{INK};-webkit-text-size-adjust:100%;">
<div style="display:none!important;visibility:hidden;opacity:0;color:transparent;height:0;width:0;max-height:0;max-width:0;overflow:hidden;mso-hide:all">{escape(preheader)}&#847;&nbsp;&#847;&nbsp;&#847;&nbsp;</div>
<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" bgcolor="{PALE}" style="width:100%;background:{PALE}">
<tr><td align="center" style="padding:36px 14px">
<table role="presentation" width="600" border="0" cellspacing="0" cellpadding="0" style="width:100%;max-width:600px;border-collapse:separate;border-spacing:0">
<tr><td bgcolor="{GREEN}" height="5" style="height:5px;background:{GREEN};font-size:0;line-height:0;border-radius:8px 8px 0 0">&nbsp;</td></tr>
<tr><td bgcolor="#ffffff" style="background:#ffffff;border-left:1px solid {LINE};border-right:1px solid {LINE};padding:22px 34px 19px">
<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0"><tr>
<td width="48" valign="middle" style="width:48px;padding-right:12px">
<img src="{LOGO_URL}" width="46" height="46" alt="Urban Farming seedling logo" style="display:block;width:46px;height:46px;border:0;border-radius:12px;background:#ffffff">
</td><td valign="middle" style="font-family:Arial,Helvetica,sans-serif">
<div style="font-size:16px;line-height:21px;font-weight:700;letter-spacing:.1px;color:{GREEN}">Urban Farming</div>
<div style="padding-top:3px;font-size:11px;line-height:15px;letter-spacing:1.1px;color:{MUTED};text-transform:uppercase">Growing better, together</div>
</td></tr></table></td></tr>
<tr><td bgcolor="#ffffff" style="background:#ffffff;border-left:1px solid {LINE};border-right:1px solid {LINE};padding:22px 34px 36px">
<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0"><tr><td style="border-top:1px solid {LINE};font-size:0;line-height:0">&nbsp;</td></tr></table>
{eyebrow_markup}<h1 style="font-family:Arial,Helvetica,sans-serif;font-size:27px;line-height:1.25;font-weight:700;letter-spacing:-.35px;color:{GREEN};margin:25px 0 18px">{escape(title)}</h1>
<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0"><tr><td style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.75;color:{INK}">{body}</td></tr>{button}</table>
</td></tr>
<tr><td bgcolor="#ffffff" style="background:#ffffff;border:1px solid {LINE};border-top:1px solid {LINE};padding:18px 34px 20px;border-radius:0 0 8px 8px">
<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0"><tr><td style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.65;color:{MUTED}">
Need a hand? Reply to this email and our team will help.<br><span style="color:{GREEN};font-weight:700">Urban Farming</span> &nbsp;·&nbsp; Growing better, together.
</td></tr></table></td></tr>
<tr><td align="center" style="padding:18px 20px 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:1.6;color:#78847a">This is a service email about your Urban Farming account or request.</td></tr>
</table></td></tr></table></body></html>'''


def _paragraph(text: str) -> str:
    return f'<p style="margin:0 0 14px">{escape(text)}</p>'


def welcome(
    *, name: str, role: str, app_url: str, confirmation_required: bool = False
) -> RenderedEmail:
    safe_name = name.strip() or "there"
    is_grower = role == "grower"
    next_step = (
        "Add your growing space and tell us what you want to grow. From there, you can request an assessment and follow the setup of your garden."
        if is_grower
        else "Complete your organization profile, then explore available local produce and tell us what your business needs."
    )
    if confirmation_required:
        next_step = (
            "Your account has been created. Confirm your email using the separate verification link we sent, then sign in to continue. "
            + next_step
        )
    title = "Welcome to Urban Farming"
    text = f"Hi {safe_name},\n\nYour {role} account is ready. {next_step}\n\nOpen your account: {app_url}\n\nIf you did not create this account, contact our support team."
    html_body = _paragraph(f"Hi {safe_name},") + _paragraph(f"Your {role} account is ready. {next_step}")
    return RenderedEmail("Welcome to Urban Farming", text, _layout(preheader=next_step, title=title, body=html_body, action=("Open your account", app_url)))


def password_reset(*, name: str, reset_url: str, expires_minutes: int = 30) -> RenderedEmail:
    title = "Reset your Urban Farming password"
    greeting = f"Hi {name.strip() or 'there'},"
    lead = "We received a request to change the password for your Urban Farming account. Use the button below to choose a new password."
    expiry = f"For your security, this link expires in {expires_minutes} minutes."
    security_note = "If you did not request a password reset, you can ignore this email. Your current password will stay the same."
    text = f"{greeting}\n\n{lead}\n\n{expiry}\n\nChoose a new password: {reset_url}\n\n{security_note}"
    expiry_card = (
        '<table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" '
        'style="margin:20px 0 2px"><tr><td style="background:#f4f7f1;border-left:3px solid #8aa56f;'
        'padding:12px 15px;color:#405648;font-size:13px;line-height:1.6">'
        f'<strong style="color:{GREEN}">Link expiry</strong><br>{escape(expiry)}</td></tr></table>'
    )
    note = (
        '<p style="margin:18px 0 0;padding-top:16px;border-top:1px solid '
        f'{LINE};font-size:13px;line-height:1.65;color:{MUTED}">{escape(security_note)}</p>'
    )
    body = _paragraph(greeting) + _paragraph(lead) + expiry_card + note
    return RenderedEmail(
        title,
        text,
        _layout(
            preheader=f"Your password reset link expires in {expires_minutes} minutes.",
            title=title,
            body=body,
            action=("Choose a new password", reset_url),
            eyebrow="Account security",
        ),
    )


def account_setup(*, name: str, setup_url: str, context: str) -> RenderedEmail:
    title = "Finish setting up your Urban Farming account"
    lead = (
        f"Hi {name.strip() or 'there'}, we created an account so you can follow {context}. "
        "Choose a password using the secure link below. It expires in 30 minutes."
    )
    text = f"{lead}\n\nSet your password: {setup_url}\n\nIf you did not request this, ignore this email."
    body = _paragraph(lead) + _paragraph("If you did not request this account, you can ignore this email.")
    return RenderedEmail(title, text, _layout(preheader="Set a password to access your grower account.", title=title, body=body, action=("Set your password", setup_url)))


def password_changed(*, name: str, app_url: str) -> RenderedEmail:
    title = "Your password was changed"
    lead = f"Hi {name.strip() or 'there'}, the password for your Urban Farming account was just changed."
    text = f"{lead}\n\nIf this was you, no action is needed. If you did not make this change, sign in to secure your account and contact support: {app_url}"
    body = _paragraph(lead) + _paragraph("If this was you, no action is needed. If you did not make this change, sign in to secure your account and contact support immediately.")
    return RenderedEmail(title, text, _layout(preheader="A security update for your account.", title=title, body=body, action=("Open your account", app_url)))


def assessment_received(*, name: str, suburb: str) -> RenderedEmail:
    title = "We received your growing space details"
    lead = f"Hi {name.strip() or 'there'}, thanks for telling us about your space in {suburb}. Our team will review the details and contact you about the next step."
    text = f"{lead}\n\nYou do not need to submit the form again. If anything changes, reply to this email."
    body = _paragraph(lead) + _paragraph("You do not need to submit the form again. If anything changes, reply to this email.")
    return RenderedEmail(title, text, _layout(preheader="Your growing space details are with our team.", title=title, body=body))


def assessment_status_update(*, name: str, suburb: str, status: str, notes: str | None, app_url: str) -> RenderedEmail:
    labels = {
        "contacted": ("Our team has contacted you", "A member of our team has reached out about your growing space."),
        "scheduled": ("Your growing space visit is being arranged", "We are arranging the next step for your growing space assessment and will be in touch with the details."),
        "assessed": ("Your growing space assessment is complete", "Our team has completed the assessment and will share recommendations with you."),
        "not_viable": ("An update on your growing space assessment", "We have reviewed the details and cannot recommend moving forward with this space at this time."),
        "closed": ("Your growing space request is closed", "This assessment request is now closed. Reply to this email if you need help or want to discuss another space."),
    }
    title, lead = labels.get(status, ("An update on your growing space", "There is an update on your growing space request."))
    greeting = f"Hi {name.strip() or 'there'},"
    location = f"Growing space: {suburb.strip()}" if suburb.strip() else ""
    note = notes.strip() if notes and notes.strip() else None
    text = "\n\n".join(part for part in (greeting, lead, location, f"Note from our team: {note}" if note else None, f"View your account: {app_url}") if part)
    body = _paragraph(greeting) + _paragraph(lead)
    if location:
        body += _paragraph(location)
    if note:
        body += _paragraph(f"Note from our team: {note}")
    return RenderedEmail(title, text, _layout(preheader=lead, title=title, body=body, action=("View your account", app_url), eyebrow="Assessment update"))


def garden_request_received(*, name: str, garden_name: str, app_url: str) -> RenderedEmail:
    title = "Your garden request is in"
    lead = f"Hi {name.strip() or 'there'}, we received your request for {garden_name}. Our team will review it and arrange the next step with you. Your request is not approved or active yet."
    text = f"{lead}\n\nYou can follow your account here: {app_url}\nIf you did not submit this request, reply to this email."
    body = _paragraph(lead) + _paragraph("You can follow progress from your Urban Farming account.")
    return RenderedEmail(title, text, _layout(preheader="Your request has been received; we will follow up with next steps.", title=title, body=body, action=("View your account", app_url)))


def garden_status(*, name: str, garden_name: str, status: str, details: str, app_url: str) -> RenderedEmail:
    labels = {
        "inspection_scheduled": "A site visit has been scheduled",
        "accepted": "Your garden request was approved",
        "rejected": "An update on your garden request",
        "live": "Your garden is ready to track",
    }
    title = labels.get(status, "An update on your garden request")
    lead = f"Hi {name.strip() or 'there'}, there is an update for {garden_name}."
    text = f"{lead}\n\n{details}\n\nOpen your account: {app_url}"
    body = _paragraph(lead) + _paragraph(details)
    return RenderedEmail(title, f"{title}\n\n{text}", _layout(preheader=f"An update for {garden_name}.", title=title, body=body, action=("View request", app_url)))


def inspector_application_received(*, name: str) -> RenderedEmail:
    title = "We received your inspector application"
    lead = f"Hi {name.strip() or 'there'}, thank you for applying to work with Urban Farming. Our team will review your experience and availability and email you when there is an update."
    text = f"{lead}\n\nThere is no need to submit another application."
    body = _paragraph(lead) + _paragraph("There is no need to submit another application.")
    return RenderedEmail(title, text, _layout(preheader="Your inspector application is with our team.", title=title, body=body, eyebrow="Application update"))


def inspector_application_status(*, name: str, status: str, notes: str | None, app_url: str) -> RenderedEmail:
    labels = {
        "under_review": ("Your inspector application is under review", "Our team is reviewing your application. We will email you with the next step."),
        "approved": ("Your inspector application was approved", "Welcome to the Urban Farming inspector network. Sign in to review your account and next steps."),
        "rejected": ("An update on your inspector application", "Thank you for your interest in the Urban Farming inspector network. We are unable to move forward with your application at this time."),
    }
    title, lead = labels.get(status, ("An update on your inspector application", "There is an update on your inspector application."))
    greeting = f"Hi {name.strip() or 'there'},"
    note = notes.strip() if notes and notes.strip() else None
    text = f"{greeting}\n\n{lead}" + (f"\n\nNote from our team: {note}" if note else "") + f"\n\nOpen your account: {app_url}"
    body = _paragraph(greeting) + _paragraph(lead)
    if note:
        body += _paragraph(f"Note from our team: {note}")
    return RenderedEmail(title, text, _layout(preheader=lead, title=title, body=body, action=("Open your account", app_url), eyebrow="Application update"))


def order_status_update(*, name: str, order_reference: str, status: str, app_url: str) -> RenderedEmail:
    labels = {
        "confirmed": ("Your produce order is confirmed", "The grower has confirmed your order and will prepare it."),
        "fulfilling": ("Your produce order is being prepared", "Your order is being prepared for collection or delivery."),
        "shipped": ("Your produce order is on its way", "Your order has been marked as shipped."),
        "delivered": ("Your produce order was delivered", "Your order has been marked as delivered. We hope you enjoy it."),
        "cancelled": ("Your produce order was cancelled", "This order has been cancelled. Contact our team if you need help."),
    }
    title, lead = labels.get(status, ("An update on your produce order", "There is an update on your produce order."))
    greeting = f"Hi {name.strip() or 'there'},"
    reference = f"Order reference: {order_reference}"
    text = f"{greeting}\n\n{lead}\n\n{reference}\n\nView your account: {app_url}"
    body = _paragraph(greeting) + _paragraph(lead) + _paragraph(reference)
    return RenderedEmail(title, text, _layout(preheader=f"{lead} {reference}", title=title, body=body, action=("View your orders", app_url), eyebrow="Order update"))


def order_received(*, name: str, order_reference: str, app_url: str) -> RenderedEmail:
    title = "We received your produce order"
    greeting = f"Hi {name.strip() or 'there'},"
    lead = "Your order request is with our team. It is pending confirmation, and we will email you when its status changes."
    reference = f"Order reference: {order_reference}"
    text = f"{greeting}\n\n{lead}\n\n{reference}\n\nView your orders: {app_url}"
    body = _paragraph(greeting) + _paragraph(lead) + _paragraph(reference)
    return RenderedEmail(title, text, _layout(preheader=lead, title=title, body=body, action=("View your orders", app_url), eyebrow="Order received"))


def contact_received(*, name: str, subject: str) -> RenderedEmail:
    title = "We received your message"
    lead = f"Hi {name.strip() or 'there'}, your message about {subject.strip() or 'Urban Farming'} has reached our team. We will reply to the email address you provided."
    text = f"{lead}\n\nYou do not need to submit the form again."
    body = _paragraph(lead) + _paragraph("You do not need to submit the form again.")
    return RenderedEmail(title, text, _layout(preheader="Your message is with the Urban Farming team.", title=title, body=body))
