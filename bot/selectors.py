"""
Centralized Playwright selectors.
Prioritizes: Accessible roles > visible text > placeholders > CSS classes

NOTE: Playwright sync API doesn't support comma-separated selectors in single string.
Instead, we use:
  1. OR chaining: locator(selector1).or(locator(selector2))
  2. Or handle multiple attempts in code
"""

class LoginSelectors:
    # Primary selectors tried in order
    USERNAME_INPUT = 'input[placeholder*="Registration"]'
    USERNAME_INPUT_FALLBACK = 'input[name="registration_no"]'
    USERNAME_INPUT_FALLBACK_2 = 'input[name="username"]'
    USERNAME_INPUT_FALLBACK_3 = 'input[type="text"]'
    
    PASSWORD_INPUT = 'input[placeholder*="Password"]'
    PASSWORD_INPUT_FALLBACK = 'input[name="password"]'
    PASSWORD_INPUT_FALLBACK_2 = 'input[type="password"]'
    
    LOGIN_BTN = 'button:has-text("Login")'
    LOGIN_BTN_FALLBACK = '#login_btn'
    LOGIN_BTN_FALLBACK_2 = 'button[type="submit"]'

class SidebarSelectors:
    # Primary: direct link to academic feedback page in left menu.
    FEEDBACK_LINK = 'a[href*="/student/academicfeedback"]'
    FEEDBACK_LINK_FALLBACK_1 = 'a.nav-link.nav-toggle:has(span.title:has-text("Feedback"))'
    FEEDBACK_LINK_FALLBACK_2 = 'a:has-text("Feedback")'
    FEEDBACK_LINK_FALLBACK_3 = '.feedback-toggle-btn'

    # Dashboard markers used for post-login verification.
    DASHBOARD_SIDEBAR = '.page-sidebar-menu'
    FEEDBACK_DASHBOARD_TITLE = 'text=Feedback Dashboard'
    DASHBOARD_GREETING_MORNING = 'text=Good Morning!'
    DASHBOARD_GREETING_AFTERNOON = 'text=Good Afternoon!'
    DASHBOARD_GREETING_EVENING = 'text=Good Evening!'

class FeedbackDashboardSelectors:
    # Subject cards - try multiple class names
    SUBJECT_CARD_PRIMARY = '.subject-card'
    SUBJECT_CARD_FALLBACK_1 = 'tr.subject-row'
    SUBJECT_CARD_FALLBACK_2 = 'h4.subject-name'
    SUBJECT_CARD_FALLBACK_3 = 'div[onclick*="subject"]'
    
    # Give Feedback button
    GIVE_FEEDBACK_BTN = 'button:has-text("Give Feedback")'
    GIVE_FEEDBACK_BTN_FALLBACK = 'a:has-text("Give Feedback")'
    GIVE_FEEDBACK_BTN_FALLBACK_2 = 'button:has-text("Give feedback")'  # lowercase variant
    
class FeedbackFormSelectors:
    # Submit button
    SUBMIT_BTN = 'button:has-text("Submit Feedback")'
    SUBMIT_BTN_FALLBACK = 'button:has-text("Submit")'
    SUBMIT_BTN_FALLBACK_2 = 'button[type="submit"]'
    
    # Already submitted detection
    ALREADY_SUBMITTED_BANNER = '.feedback-already-given:visible'
    ALREADY_SUBMITTED_TEXT = '.feedback-already-given:visible p:has-text("already provided feedback")'

    # Date-level error after clicking Give Feedback
    NO_CLASSES_FOR_DATE_ERROR = '#toast-container .toast.toast-error .toast-message:has-text("No classes found for this subject on the selected date.")'
    FEEDBACK_ERROR_TITLE = '#toast-container .toast.toast-error .toast-title:has-text("Feedback Error")'
    CLOSE_BTN = 'button:has-text("Close")'
