#!/usr/bin/env python3
"""
Surveille le formulaire de réservation telc (KBW Personal Services) pour
Douala et Yaoundé, B1 et B2, et envoie des e-mails dès que le message
"créneaux complets" disparaît ou qu'une date apparaît dans le menu "événement".

Installation (une fois) :
    pip install playwright
    playwright install chromium

Variables d'environnement (Gmail : mot de passe d'application) :
    SMTP_USER, SMTP_PASS, MAIL_TO (optionnel)

Lancement :
    python telc_watch.py          # surveillance
    python telc_watch.py --test   # envoie un e-mail de test et quitte
    python telc_watch.py --once   # une seule vérification (pour GitHub Actions)

MAIL_TO accepte plusieurs adresses séparées par des virgules.
"""
import os
import re
import smtplib
import sys
import time
from email.message import EmailMessage

from playwright.sync_api import sync_playwright

BOOKCART = "https://kbw-personal-services.butlerapp2.de/demo#/bookcart"

# (nom affiché, ville, niveau) -> repéré dans le texte des options du menu "Type d'événement"
TARGETS = [
    ("Douala B2", "douala", "b2"),
    ("Douala B1", "douala", "b1"),
    ("Yaoundé B2", "yaound", "b2"),
    ("Yaoundé B1", "yaound", "b1"),
]

CHECK_EVERY = 60
MAILS_PER_ROUND = 5
MAX_ROUNDS = 5
CLOSED = re.compile(r"(déjà complets|complets|ausgebucht|bereits belegt|sold out)", re.I)

SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
MAIL_TO = os.environ.get("MAIL_TO", SMTP_USER)


def send_mail(subject, body):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = SMTP_USER, MAIL_TO, subject
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)


def check(page, city, level):
    """Retourne (ouvert: bool, dates: list[str], infos: str)."""
    page.goto(BOOKCART, wait_until="networkidle", timeout=60000)
    page.wait_for_selector("select", timeout=30000)
    type_sel = page.locator("select").first
    labels = type_sel.locator("option").all_text_contents()
    idx = next((i for i, t in enumerate(labels)
                if city in t.lower() and re.search(rf"\b{level}\b", t.lower())), None)
    if idx is None:
        return False, [], f"Option introuvable dans le menu. Options vues : {labels}"
    type_sel.select_option(index=idx)
    page.wait_for_timeout(3000)

    text = page.inner_text("body")
    dates = []
    if page.locator("select").count() > 1:
        opts = page.locator("select").nth(1).locator("option").all_text_contents()
        dates = [o.strip() for o in opts if o.strip() and "sélectionnez" not in o.lower()]
    closed_msg = bool(CLOSED.search(text))
    is_open = bool(dates) or not closed_msg
    return is_open, dates, text[:600]


def main():
    if "--test" in sys.argv:
        send_mail("TELC watch : test", "Les e-mails fonctionnent.")
        print("E-mail de test envoyé.")
        return
    rounds = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="fr-FR")
        page = ctx.new_page()
        while True:
            for name, city, level in TARGETS:
                try:
                    is_open, dates, info = check(page, city, level)
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] {name}: erreur {e}")
                    continue
                print(f"[{time.strftime('%H:%M:%S')}] {name}: ouvert={is_open} dates={dates}")
                if is_open and rounds.get(name, 0) < MAX_ROUNDS:
                    rounds[name] = rounds.get(name, 0) + 1
                    for i in range(MAILS_PER_ROUND):
                        send_mail(
                            f"TELC {name} : PLACES DISPONIBLES ? ({i+1}/{MAILS_PER_ROUND})",
                            f"Le message 'complet' a disparu ou des dates sont proposées.\n"
                            f"Dates : {dates or 'non lisibles'}\n\nRéserve vite : {BOOKCART}\n\n{info}",
                        )
                        time.sleep(60 / MAILS_PER_ROUND)
                elif not is_open:
                    rounds[name] = 0
            if "--once" in sys.argv:
                return
            time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main()
