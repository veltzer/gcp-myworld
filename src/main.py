"""
Run the development server: `python src/main.py`.
"""

from myworld import create_app

if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8080, debug=True)
