"""
Helper script to extract Plaud access token.

This script provides instructions and a Selenium-based approach
to automatically extract the token from Plaud web app.

Option 1: Manual extraction (recommended for first time)
Option 2: Selenium automation (requires Chrome and chromedriver)
"""

import json
import sys


def print_manual_instructions():
    """Print manual instructions for getting the token."""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║           HOW TO GET YOUR PLAUD ACCESS TOKEN                     ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. Open your browser and go to: https://web.plaud.ai            ║
║                                                                  ║
║  2. Log in with your Plaud account                               ║
║                                                                  ║
║  3. Open Developer Tools:                                        ║
║     - Chrome/Edge: Press F12 or Ctrl+Shift+I                     ║
║     - Firefox: Press F12 or Ctrl+Shift+I                         ║
║     - Safari: Enable Developer menu, then Cmd+Option+I           ║
║                                                                  ║
║  4. Go to the "Application" tab (Chrome) or "Storage" (Firefox)  ║
║                                                                  ║
║  5. In the left sidebar, expand "Local Storage"                  ║
║                                                                  ║
║  6. Click on "https://web.plaud.ai"                              ║
║                                                                  ║
║  7. Look for one of these keys:                                  ║
║     - access_token                                               ║
║     - token                                                      ║
║     - auth_token                                                 ║
║                                                                  ║
║  8. Copy the VALUE (the long string, not the key name)           ║
║                                                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  ALTERNATIVE: Check Network requests                             ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. With DevTools open, go to the "Network" tab                  ║
║                                                                  ║
║  2. Refresh the page or click on a recording                     ║
║                                                                  ║
║  3. Look for requests to "api.plaud.ai"                          ║
║                                                                  ║
║  4. Click on a request and find the "Authorization" header       ║
║                                                                  ║
║  5. Copy the token (everything after "Bearer ")                  ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝

Once you have the token, save it to Google Secret Manager:

    echo -n 'YOUR_TOKEN_HERE' | gcloud secrets versions add plaud-token --data-file=-

Or for local testing, add to your .env file:

    PLAUD_ACCESS_TOKEN=your_token_here
""")


def extract_with_selenium(email: str, password: str) -> str:
    """
    Extract token using Selenium automation.

    Requires: pip install selenium webdriver-manager
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.chrome.service import Service
    except ImportError:
        print("Selenium not installed. Run: pip install selenium webdriver-manager")
        sys.exit(1)

    print("Launching Chrome...")

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run without visible browser
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        print("Navigating to Plaud web app...")
        driver.get("https://web.plaud.ai")

        # Wait for page to load and look for login form
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Try to find and fill login form
        # Note: Actual selectors may vary - inspect the page to find correct ones
        try:
            email_input = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email']"))
            )
            email_input.send_keys(email)

            password_input = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
            password_input.send_keys(password)

            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()

            print("Logging in...")

            # Wait for login to complete
            WebDriverWait(driver, 15).until(
                lambda d: "login" not in d.current_url.lower()
            )
        except Exception as e:
            print(f"Login form interaction failed: {e}")
            print("You may need to login manually first.")

        # Extract token from localStorage
        print("Extracting token from localStorage...")

        token = driver.execute_script("""
            return localStorage.getItem('access_token') ||
                   localStorage.getItem('token') ||
                   localStorage.getItem('auth_token') ||
                   localStorage.getItem('plaud_token');
        """)

        if token:
            print(f"\n✓ Token extracted successfully!")
            print(f"Token (first 50 chars): {token[:50]}...")
            return token
        else:
            print("✗ Could not find token in localStorage")
            print("\nTry manual extraction instead.")
            return None

    finally:
        driver.quit()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract Plaud access token")
    parser.add_argument("--auto", action="store_true",
                       help="Attempt automatic extraction with Selenium")
    parser.add_argument("--email", help="Plaud account email (for auto mode)")
    parser.add_argument("--password", help="Plaud account password (for auto mode)")

    args = parser.parse_args()

    if args.auto:
        if not args.email or not args.password:
            print("Error: --email and --password required for auto mode")
            sys.exit(1)
        token = extract_with_selenium(args.email, args.password)
        if token:
            print(f"\nFull token:\n{token}")
    else:
        print_manual_instructions()
