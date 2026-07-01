# app/services/email_service.py
import logging
import html
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Shared SMTP sender ─────────────────────────────────────────────────────


def _send_email(msg: MIMEMultipart, to_email: str, email_type: str) -> None:
    """
    Core SMTP sender shared by all email types.

    Args:
        msg: The fully assembled MIME message (headers + body already attached).
        to_email: Recipient email address.
        email_type: Human-readable label for logging (e.g. "OTP", "password reset").

    Raises:
        RuntimeError: if SMTP credentials are not configured.
        smtplib.SMTPException: on SMTP-level errors (connection, auth, etc.).
    """
    if not settings.SMTP_FROM_EMAIL:
        raise RuntimeError(
            "SMTP_FROM_EMAIL is not configured. "
            "Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, "
            "SMTP_FROM_EMAIL in your .env file."
        )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            server.ehlo()
            if settings.SMTP_USE_TLS:
                server.starttls()
                server.ehlo()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(
                settings.SMTP_FROM_EMAIL,
                to_email,
                msg.as_string(),
            )

        logger.info("%s email sent to %s", email_type, to_email)

    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP authentication failed (%s): %s", email_type, exc)
        raise RuntimeError(
            "Email authentication failed. "
            "Check SMTP_USER and SMTP_PASSWORD in your .env file. "
            "For Gmail, use an App Password, not your login password."
        ) from exc

    except smtplib.SMTPConnectError as exc:
        logger.error(
            "SMTP connection failed (%s) for %s:%s: %s",
            email_type,
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            exc,
        )
        raise RuntimeError(
            f"Cannot connect to SMTP server at {settings.SMTP_HOST}:{settings.SMTP_PORT}. "
            "Check SMTP_HOST and SMTP_PORT in your .env file."
        ) from exc

    except Exception as exc:
        logger.error("Failed to send %s email to %s: %s", email_type, to_email, exc)
        raise


# ── OTP (Signup Verification) Email ────────────────────────────────────────


def _build_otp_email(to_email: str, full_name: str, otp: str) -> MIMEMultipart:
    safe_name = html.escape(full_name)
    expire_minutes = max(1, settings.OTP_EXPIRE_SECONDS // 60)
    expire_label = f"{expire_minutes} minute{'s' if expire_minutes != 1 else ''}"
    text_body = (
        f"Hi {safe_name},\n\n"
        f"Your GeoMap verification code is: {otp}\n\n"
        f"This code expires in {expire_label}.\n\n"
        f"If you did not request this code, ignore this email.\n\n"
        f"— The GeoMap Team"
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>GeoMap Verification</title>
</head>
<body style="margin:0; padding:0; background-color:#f2f4f8;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
             Helvetica,Arial,sans-serif;">

  <!--[if mso]>
  <table role="presentation" width="600" align="center" cellpadding="0"
         cellspacing="0" border="0"><tr><td>
  <![endif]-->

  <!-- Outer wrapper -->
  <table role="presentation" align="center" border="0" cellpadding="0"
         cellspacing="0" width="100%%"
         style="max-width:560px; margin:40px auto; border-collapse:collapse;">

    <!-- ── Header ── -->
    <tr>
      <td style="background-color:#1a56b0; border-radius:8px 8px 0 0;
                 padding:28px 32px; text-align:center;">
        <p style="margin:0; font-size:11px; font-weight:600;
                  letter-spacing:3px; color:#a8c8f0;
                  text-transform:uppercase;">GeoMap</p>
        <p style="margin:6px 0 0; font-size:20px; font-weight:600;
                  color:#ffffff; letter-spacing:0.3px;">Verify your identity</p>
      </td>
    </tr>

    <!-- ── Body card ── -->
    <tr>
      <td style="background-color:#ffffff; padding:36px 32px 28px;
                 border-left:1px solid #e0e4ea; border-right:1px solid #e0e4ea;">

        <!-- Greeting -->
        <p style="margin:0 0 6px; font-size:15px; color:#1a1a2e;
                  font-weight:500;">Hi {safe_name},</p>
        <p style="margin:0 0 28px; font-size:14px; color:#4a5568;
                  line-height:1.6;">
          Use the code below to complete your sign-in. Do not share it
          with anyone.
        </p>

        <!-- OTP block -->
        <table role="presentation" align="center" border="0" cellpadding="0"
               cellspacing="0" width="100%%"
               style="background-color:#f7f9fc; border:1px solid #dce3ed;
                      border-radius:8px; margin-bottom:24px;">
          <tr>
            <td style="padding:12px 16px 8px; text-align:center;">
              <p style="margin:0; font-size:10px; font-weight:600;
                        letter-spacing:2.5px; color:#8a9ab0;
                        text-transform:uppercase;">Verification code</p>
            </td>
          </tr>
          <tr>
            <td style="padding:4px 24px 20px; text-align:center;">
              <!-- Monospace, wide letter-spacing makes digits scannable -->
              <span style="display:inline-block; font-family:'Courier New',
                           Courier,monospace; font-size:40px; font-weight:700;
                           letter-spacing:14px; color:#1a1a2e;
                           padding-left:14px;">
                {otp}
              </span>
            </td>
          </tr>
        </table>

        <!-- Expiry row -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0"
               width="100%%">
          <tr>
            <td style="border-left:3px solid #1a56b0; padding:8px 14px;">
              <p style="margin:0; font-size:13px; color:#4a5568;">
                This code expires in
                <strong style="color:#1a1a2e;">{expire_label}</strong>.
              </p>
            </td>
          </tr>
        </table>

        <!-- Divider -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0"
               width="100%%" style="margin:28px 0 20px;">
          <tr>
            <td style="border-top:1px solid #e8ecf1; font-size:0;
                       line-height:0;">&nbsp;</td>
          </tr>
        </table>

        <!-- Security note -->
        <p style="margin:0; font-size:12px; color:#8a9aa8; line-height:1.6;">
          If you did not create a GeoMap account or request this code,
          you can safely ignore this email — no action is required.
        </p>

      </td>
    </tr>

    <!-- ── Footer ── -->
    <tr>
      <td style="background-color:#f7f9fc; border:1px solid #e0e4ea;
                 border-top:0; border-radius:0 0 8px 8px;
                 padding:16px 32px; text-align:center;">
        <p style="margin:0; font-size:11px; color:#a0aab8;">
          The GeoMap Team &nbsp;&bull;&nbsp;
          <a href="mailto:{settings.SMTP_FROM_EMAIL}"
             style="color:#1a56b0; text-decoration:none;">
            Contact Support
          </a>
        </p>
      </td>
    </tr>

  </table>

  <!--[if mso]></td></tr></table><![endif]-->

  <!-- Preheader — hidden preview text for inbox snippet -->
  <div style="display:none; visibility:hidden; overflow:hidden;
              max-height:0; max-width:0; opacity:0; font-size:1px;">
    Your GeoMap verification code is {otp} — valid for {expire_label}.
    &#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;
    &#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;
  </div>

</body>
</html>"""

    # ── Assemble MIME ──────────────────────────────────────────────────────
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your GeoMap verification code"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email

    # Plain-text part first; email clients prefer the last matching part
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    return msg


def send_otp_email(to_email: str, full_name: str, otp: str) -> None:
    """
    Send a 6-digit OTP to the given email address via SMTP.
    """
    msg = _build_otp_email(to_email, full_name, otp)
    _send_email(msg, to_email, "OTP")


# ── Password Reset Email ───────────────────────────────────────────────────


def _build_reset_email(to_email: str, full_name: str, otp: str) -> MIMEMultipart:
    """Build a password reset email with OTP."""
    safe_name = html.escape(full_name)
    expire_minutes = max(1, settings.OTP_EXPIRE_SECONDS // 60)
    expire_label = f"{expire_minutes} minute{'s' if expire_minutes != 1 else ''}"

    text_body = (
        f"Hi {safe_name},\n\n"
        f"You requested a password reset for your GeoMap account.\n\n"
        f"Your password reset code is: {otp}\n\n"
        f"This code expires in {expire_label}.\n\n"
        f"If you did not request a password reset, please ignore this email.\n"
        f"Your password will remain unchanged.\n\n"
        f"— The GeoMap Team"
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>GeoMap Password Reset</title>
</head>
<body style="margin:0; padding:0; background-color:#f2f4f8;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
             Helvetica,Arial,sans-serif;">

  <!--[if mso]>
  <table role="presentation" width="600" align="center" cellpadding="0"
         cellspacing="0" border="0"><tr><td>
  <![endif]-->

  <!-- Outer wrapper -->
  <table role="presentation" align="center" border="0" cellpadding="0"
         cellspacing="0" width="100%%"
         style="max-width:560px; margin:40px auto; border-collapse:collapse;">

    <!-- ── Header ── -->
    <tr>
      <td style="background-color:#1a56b0; border-radius:8px 8px 0 0;
                 padding:28px 32px; text-align:center;">
        <p style="margin:0; font-size:11px; font-weight:600;
                  letter-spacing:3px; color:#a8c8f0;
                  text-transform:uppercase;">GeoMap</p>
        <p style="margin:6px 0 0; font-size:20px; font-weight:600;
                  color:#ffffff; letter-spacing:0.3px;">Password Reset Request</p>
      </td>
    </tr>

    <!-- ── Body card ── -->
    <tr>
      <td style="background-color:#ffffff; padding:36px 32px 28px;
                 border-left:1px solid #e0e4ea; border-right:1px solid #e0e4ea;">

        <p style="margin:0 0 6px; font-size:15px; color:#1a1a2e;
                  font-weight:500;">Hi {safe_name},</p>
        <p style="margin:0 0 28px; font-size:14px; color:#4a5568;
                  line-height:1.6;">
          We received a request to reset the password for your GeoMap account.
          Use the code below to complete the process.
        </p>

        <!-- OTP block -->
        <table role="presentation" align="center" border="0" cellpadding="0"
               cellspacing="0" width="100%%"
               style="background-color:#f7f9fc; border:1px solid #dce3ed;
                      border-radius:8px; margin-bottom:24px;">
          <tr>
            <td style="padding:12px 16px 8px; text-align:center;">
              <p style="margin:0; font-size:10px; font-weight:600;
                        letter-spacing:2.5px; color:#8a9ab0;
                        text-transform:uppercase;">Reset code</p>
            </td>
          </tr>
          <tr>
            <td style="padding:4px 24px 20px; text-align:center;">
              <span style="display:inline-block; font-family:'Courier New',
                           Courier,monospace; font-size:40px; font-weight:700;
                           letter-spacing:14px; color:#1a1a2e;
                           padding-left:14px;">
                {otp}
              </span>
            </td>
          </tr>
        </table>

        <!-- Expiry row -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0"
               width="100%%">
          <tr>
            <td style="border-left:3px solid #1a56b0; padding:8px 14px;">
              <p style="margin:0; font-size:13px; color:#4a5568;">
                This code expires in
                <strong style="color:#1a1a2e;">{expire_label}</strong>.
              </p>
            </td>
          </tr>
        </table>

        <!-- Divider -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0"
               width="100%%" style="margin:28px 0 20px;">
          <tr>
            <td style="border-top:1px solid #e8ecf1; font-size:0;
                       line-height:0;">&nbsp;</td>
          </tr>
        </table>

        <p style="margin:0; font-size:12px; color:#8a9aa8; line-height:1.6;">
          If you did not request a password reset, you can safely ignore this
          email — no changes have been made to your account.
        </p>

      </td>
    </tr>

    <!-- ── Footer ── -->
    <tr>
      <td style="background-color:#f7f9fc; border:1px solid #e0e4ea;
                 border-top:0; border-radius:0 0 8px 8px;
                 padding:16px 32px; text-align:center;">
        <p style="margin:0; font-size:11px; color:#a0aab8;">
          The GeoMap Team &nbsp;&bull;&nbsp;
          <a href="mailto:{settings.SMTP_FROM_EMAIL}"
             style="color:#1a56b0; text-decoration:none;">
            Contact Support
          </a>
        </p>
      </td>
    </tr>

  </table>

  <!--[if mso]></td></tr></table><![endif]-->

  <div style="display:none; visibility:hidden; overflow:hidden;
              max-height:0; max-width:0; opacity:0; font-size:1px;">
    Your GeoMap password reset code is {otp} — valid for {expire_label}.
    &#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;
    &#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;
  </div>

</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your GeoMap password reset code"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    return msg


def send_reset_email(to_email: str, full_name: str, otp: str) -> None:
    """
    Send a password reset OTP to the given email address via SMTP.
    """
    msg = _build_reset_email(to_email, full_name, otp)
    _send_email(msg, to_email, "password reset")


# ── Payment Confirmation Email ────────────────────────────────────────────────


def _build_payment_confirmation_email(
    to_email: str,
    full_name: str,
    credits_purchased: int,
    new_balance: int,
    amount_inr: int,
) -> MIMEMultipart:
    """Build a receipt-style payment confirmation email."""
    safe_name = html.escape(full_name)

    text_body = (
        f"Hi {safe_name},\n\n"
        f"Thank you for your purchase!\n\n"
        f"Amount: ₹{amount_inr}\n"
        f"Credits purchased: {credits_purchased}\n"
        f"New credit balance: {new_balance}\n\n"
        f"You can now use your credits for AI chat, place Q&A, and other features.\n\n"
        f"— The GeoMap Team"
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>GeoMap Payment Confirmation</title>
</head>
<body style="margin:0; padding:0; background-color:#f2f4f8;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
             Helvetica,Arial,sans-serif;">

  <!--[if mso]>
  <table role="presentation" width="600" align="center" cellpadding="0"
         cellspacing="0" border="0"><tr><td>
  <![endif]-->

  <table role="presentation" align="center" border="0" cellpadding="0"
         cellspacing="0" width="100%%"
         style="max-width:560px; margin:40px auto; border-collapse:collapse;">

    <!-- ── Header ── -->
    <tr>
      <td style="background-color:#1a56b0; border-radius:8px 8px 0 0;
                 padding:28px 32px; text-align:center;">
        <p style="margin:0; font-size:11px; font-weight:600;
                  letter-spacing:3px; color:#a8c8f0;
                  text-transform:uppercase;">GeoMap</p>
        <p style="margin:6px 0 0; font-size:20px; font-weight:600;
                  color:#ffffff; letter-spacing:0.3px;">Payment Confirmed</p>
      </td>
    </tr>

    <!-- ── Body card ── -->
    <tr>
      <td style="background-color:#ffffff; padding:36px 32px 28px;
                 border-left:1px solid #e0e4ea; border-right:1px solid #e0e4ea;">

        <p style="margin:0 0 24px; font-size:15px; color:#1a1a2e;">
          Hi {safe_name},
        </p>
        <p style="margin:0 0 24px; font-size:14px; color:#4a5568; line-height:1.6;">
          Thank you for your purchase! Your credits have been added to your account.
        </p>

        <!-- Receipt block -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0"
               width="100%%"
               style="background-color:#f7f9fc; border:1px solid #dce3ed;
                      border-radius:8px; margin-bottom:24px;">
          <tr>
            <td style="padding:16px 20px;">
              <table role="presentation" border="0" cellpadding="0"
                     cellspacing="0" width="100%%">
                <tr>
                  <td style="padding:6px 0; font-size:13px; color:#8a9ab0;">
                    Amount paid
                  </td>
                  <td style="padding:6px 0; font-size:15px; font-weight:600;
                             color:#1a1a2e; text-align:right;">
                    ₹{amount_inr}
                  </td>
                </tr>
                <tr>
                  <td style="padding:6px 0; font-size:13px; color:#8a9ab0;
                             border-top:1px solid #e8ecf1;">
                    Credits purchased
                  </td>
                  <td style="padding:6px 0; font-size:15px; font-weight:600;
                             color:#1a56b0; text-align:right;
                             border-top:1px solid #e8ecf1;">
                    +{credits_purchased}
                  </td>
                </tr>
                <tr>
                  <td style="padding:6px 0; font-size:13px; color:#8a9ab0;
                             border-top:1px solid #e8ecf1;">
                    New balance
                  </td>
                  <td style="padding:6px 0; font-size:15px; font-weight:700;
                             color:#1a1a2e; text-align:right;
                             border-top:1px solid #e8ecf1;">
                    {new_balance} credits
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>

        <p style="margin:0 0 4px; font-size:13px; color:#4a5568; line-height:1.6;">
          You can now use your credits for AI-powered chat, place Q&A,
          and other GeoMap features.
        </p>

        <table role="presentation" border="0" cellpadding="0" cellspacing="0"
               width="100%%" style="margin:28px 0 20px;">
          <tr>
            <td style="border-top:1px solid #e8ecf1; font-size:0;
                       line-height:0;">&nbsp;</td>
          </tr>
        </table>

        <p style="margin:0; font-size:12px; color:#8a9aa8; line-height:1.6;">
          If you have any questions about this purchase, please contact our support team.
        </p>

      </td>
    </tr>

    <!-- ── Footer ── -->
    <tr>
      <td style="background-color:#f7f9fc; border:1px solid #e0e4ea;
                 border-top:0; border-radius:0 0 8px 8px;
                 padding:16px 32px; text-align:center;">
        <p style="margin:0; font-size:11px; color:#a0aab8;">
          The GeoMap Team &nbsp;&bull;&nbsp;
          <a href="mailto:{settings.SMTP_FROM_EMAIL}"
             style="color:#1a56b0; text-decoration:none;">
            Contact Support
          </a>
        </p>
      </td>
    </tr>

  </table>

  <!--[if mso]></td></tr></table><![endif]-->

  <div style="display:none; visibility:hidden; overflow:hidden;
              max-height:0; max-width:0; opacity:0; font-size:1px;">
    GeoMap payment confirmed — ₹{amount_inr} · {credits_purchased} credits added.
    &#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;
  </div>

</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"GeoMap — Payment Confirmed · +{credits_purchased} credits"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    return msg


def send_payment_confirmation_email(
    to_email: str,
    full_name: str,
    credits_purchased: int,
    new_balance: int,
    amount_inr: int,
) -> None:
    """
    Send a payment confirmation / receipt email.
    """
    msg = _build_payment_confirmation_email(
        to_email, full_name, credits_purchased, new_balance, amount_inr
    )
    _send_email(msg, to_email, "payment confirmation")
