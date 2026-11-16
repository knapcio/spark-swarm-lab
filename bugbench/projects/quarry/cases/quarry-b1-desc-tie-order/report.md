# Descending sort scrambles the order of tied rows

Our league table sorts teams in descending order and players by name:

```python
from quarry import Engine

db = Engine()
db.run_script("CREATE TABLE scores (player TEXT, team TEXT, points INTEGER);"
              "INSERT INTO scores VALUES ('Ola', 'red', 90), ('Bart', 'blue', 75), ('Celina', 'red', 90), "
              "('Dawid', 'blue', 90), ('Ewa', 'red', 60), ('Filip', 'blue', 75)")
db.query("SELECT player FROM scores ORDER BY team DESC, player")
```

Expected: Celina, Ewa, Ola, Bart, Dawid, Filip (red before blue, names A to Z
inside each team).
Actual: Ola, Ewa, Celina, Filip, Dawid, Bart. The names come out Z to A
inside each team.

`ORDER BY points DESC` on the same table should keep tied players in table
order (Ola, Celina, Dawid, Bart, Filip, Ewa) but gives Dawid, Celina, Ola,
Filip, Bart, Ewa. Ascending sorts look fine. The README says sorting is
stable in both directions.
