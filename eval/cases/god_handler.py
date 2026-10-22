import smtplib

import psycopg2


def handle_signup(form: dict) -> str:
    conn = psycopg2.connect("dbname=app user=app")  # expect: architecture
    cur = conn.cursor()
    cur.execute("INSERT INTO users (email) VALUES (%s)", (form["email"],))
    conn.commit()
    server = smtplib.SMTP("smtp.example.com")
    server.sendmail("noreply@example.com", form["email"], "Welcome!")
    return "<h1>Thanks for signing up</h1>"
