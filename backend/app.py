from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy

# Keep frontend flat: serve templates + static from the same folder
app = Flask(
    __name__,
    template_folder="../frontend",
    static_folder="../frontend",
    static_url_path=""   # exposes static at site root so ./style.css works
)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///occt.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
