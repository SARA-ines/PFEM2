import json
import random


with open("ticket_metadata.json", "r", encoding="utf-8") as f:
    all_tickets = json.load(f)


def has_good_solution(ticket):
    solution_text = ticket.get("full_text", "")
    if "Solution:" not in solution_text:
        return False
    solution = solution_text.split("Solution:", 1)[1].strip()
    bad_markers = ["en attente", "merci de nous", "votre demande", "bien recu", "bonjour mr"]
    return len(solution) > 30 and not any(marker in solution.lower() for marker in bad_markers)


good = [ticket for ticket in all_tickets if has_good_solution(ticket)]
print(f"Tickets utiles : {len(good)}")

random.seed(42)
random.shuffle(good)

split = int(len(good) * 0.8)
train = good[:split]
test = good[split:]

with open("ticket_train.json", "w", encoding="utf-8") as f:
    json.dump(train, f, ensure_ascii=False, indent=2)

with open("ticket_test.json", "w", encoding="utf-8") as f:
    json.dump(test, f, ensure_ascii=False, indent=2)

print(f"Train : {len(train)} tickets")
print(f"Test  : {len(test)} tickets")
print("Fichiers créés : ticket_train.json + ticket_test.json")
