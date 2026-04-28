import faiss
import json
import numpy as np
from sentence_transformers import SentenceTransformer

index = faiss.read_index("ticket_index.faiss")

with open("ticket_metadata.json", "r", encoding="utf-8") as f:
    data = json.load(f)

model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

question = input("Pose ta question : ")

question_vector = model.encode([question])
question_vector = np.array(question_vector).astype("float32")

k = 3
distances, indices = index.search(question_vector, k)

print("\nRésultats trouvés :")

for i, idx in enumerate(indices[0]):
    result = data[idx]
    full_text = result["full_text"]

    solution = "Solution non trouvée"
    if "Solution:" in full_text:
        solution = full_text.split("Solution:", 1)[1].strip()

    print(f"\nRésultat {i+1}")
    print("Ticket :", result["ticket_id"])
    print("Objet :", result["objet"])
    print("Distance :", distances[0][i])
    print("Solution proposée :")
    print(solution[:500])