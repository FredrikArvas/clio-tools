"""
patch_handlers_routing.py — utökar ssf@-routing till coded/auto_send-nivå
Körs en gång på servern: python3 patch_handlers_routing.py
"""
from pathlib import Path

p = Path(__file__).parent / "clio-agent-mail" / "handlers.py"
src = p.read_text(encoding="utf-8")

old = (
    "        elif clf.action == classifier.ACTION_FAQ_CHECK:\n"
    "            _handle_faq(mail_item, clf, config, dry_run)\n"
    "\n"
    "        elif clf.action == classifier.ACTION_AUTO_SEND:\n"
    "            _handle_auto_send(mail_item, clf, config, dry_run)"
)

new = (
    "        elif clf.action == classifier.ACTION_FAQ_CHECK:\n"
    "            if clf.account_key == \"ssf\":\n"
    "                _handle_rag_query(mail_item, clf, config, dry_run)\n"
    "            else:\n"
    "                _handle_faq(mail_item, clf, config, dry_run)\n"
    "\n"
    "        elif clf.action == classifier.ACTION_AUTO_SEND:\n"
    "            if clf.account_key == \"ssf\":\n"
    "                _handle_rag_query(mail_item, clf, config, dry_run)\n"
    "            else:\n"
    "                _handle_auto_send(mail_item, clf, config, dry_run)"
)

assert old in src, "Hittade inte dispatch-blocket!"
src = src.replace(old, new, 1)

p.write_text(src, encoding="utf-8")
print(f"OK — routing uppdaterad ({len(src)} tecken)")
