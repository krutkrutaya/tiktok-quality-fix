"""Allow running as: python -m tiktok_quality"""
import sys

if "--gui" in sys.argv:
    from .gui import main as gui_main
    gui_main()
else:
    from .cli import main as cli_main
    cli_main()
