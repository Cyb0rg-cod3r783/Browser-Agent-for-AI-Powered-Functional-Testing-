from sqlalchemy import create_engine, text

engine = create_engine('mysql+mysqlconnector://root:admin@localhost/selenium')
conn = engine.connect()

print("=" * 80)

print("WORKFLOWS")
print("=" * 80)
rows = conn.execute(text('SELECT id, name, url, created_at FROM workflows ORDER BY id DESC')).fetchall()
for r in rows:
    print(f"  ID: {r[0]}  |  {r[1]}  |  {r[2]}  |  {r[3]}")

print()
print("=" * 80)
print("WORKFLOW STEPS")
print("=" * 80)
steps = conn.execute(text('SELECT id, workflow_id, step_order, action, value, selector FROM workflow_steps ORDER BY workflow_id, step_order')).fetchall()
for s in steps:
    val = str(s[4])[:50] if s[4] else "None"
    sel = str(s[5])[:80] if s[5] else "None"
    print(f"  Step {s[2]} (Workflow #{s[1]}):  action={s[3]}  |  value={val}  |  selector={sel}")

print()
print("=" * 80)
print("ELEMENTS")
print("=" * 80)
elements = conn.execute(text('SELECT id, page_id, element_type, text, selector FROM elements ORDER BY id')).fetchall()
for e in elements:
    txt = str(e[3])[:40] if e[3] else "None"
    sel = str(e[4])[:80] if e[4] else "None"
    print(f"  Element #{e[0]} (Page #{e[1]}):  type={e[2]}  |  text={txt}  |  selector={sel}")

print()
print("=" * 80)
print("PAGES")
print("=" * 80)
pages = conn.execute(text('SELECT id, url FROM pages ORDER BY id')).fetchall()
for p in pages:
    print(f"  Page #{p[0]}:  {p[1]}")

conn.close()
