"""
Evaluation harness — gold sets, machine-assisted labeling tooling, and scoring
scripts. See backend/eval/README.md for the full protocol and `make eval-*`
targets.
"""

from dotenv import load_dotenv

load_dotenv()  # scripts run standalone (not via app.main), so load backend/.env here
