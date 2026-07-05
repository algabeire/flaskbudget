with open("app.py", "r") as f:
    text = f.read()

# Locate the exact broken text block and replace it cleanly
bad_str = 'app.config['\''SQLALCHEMY_DATABASE_URI'\''] = "postgresql://postgres.wlktrcyuvlwheuqohdxs:Qaaqaay1000@://supabase.com"'
good_str = 'app.config['\''SQLALCHEMY_DATABASE_URI'\''] = "postgresql://postgres.wlktrcyuvlwheuqohdxs:Qaaqaay1000@://supabase.com"'

if bad_str in text:
    text = text.replace(bad_str, good_str)
else:
    # If the text was slightly different, force replace any variant on line 25
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "SQLALCHEMY_DATABASE_URI" in line:
            lines[i] = 'app.config['\''SQLALCHEMY_DATABASE_URI'\''] = "postgresql://postgres.wlktrcyuvlwheuqohdxs:Qaaqaay1000@://supabase.com"'
    text = "\n".join(lines)

with open("app.py", "w") as f:
    f.write(text)
print("Database address replaced successfully.")
