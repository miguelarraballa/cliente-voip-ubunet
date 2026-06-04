import logging
from app import VoIPApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

if __name__ == "__main__":
    app = VoIPApp()
    app.mainloop()
