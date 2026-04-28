import re


def _clean_ticket_text(text: str) -> str:
    cleaned = " ".join((text or "").replace("\r", " ").replace("\n", " ").split())
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    return cleaned.strip(" ,;:")


def rewrite_rag_solution(objet: str, solution: str, module: str = "", type_incident: str = "") -> str:
    clean_objet = _clean_ticket_text(objet)
    clean_solution = _clean_ticket_text(solution)

    if not clean_solution:
        if clean_objet:
            return f"Un cas similaire a ete retrouve concernant {clean_objet}."
        return "Un cas similaire a ete retrouve, mais la solution associee n'est pas detaillee."

    solution_low = clean_solution.lower()
    if "aucune anomalie" in solution_low:
        if clean_objet:
            return (
                f"Apres verification concernant {clean_objet}, aucune anomalie n'a ete constatee. "
                "Les donnees paraissent coherentes."
            )
        return "Apres verification, aucune anomalie n'a ete constatee."

    if module and type_incident:
        return (
            f"Un cas similaire a ete retrouve sur le module {module} pour un incident de type "
            f"{type_incident}. Solution proposee : {clean_solution}"
        )

    if module:
        return f"Un cas similaire a ete retrouve sur le module {module}. Solution proposee : {clean_solution}"

    return f"Un cas similaire a ete retrouve. Solution proposee : {clean_solution}"


def apply_business_logic(llm_result: dict, nlp_result: dict, context: dict) -> dict:
    confidence = llm_result.get("confidence_score", 0.5)
    nlp_confidence = nlp_result.get("confidence", 0.5)
    has_similar = bool(llm_result.get("_had_similar_tickets", False))
    best_similarity = float(llm_result.get("_best_similarity", 0.0) or 0.0)

    if not has_similar or best_similarity < 0.12:
        llm_result["solution_proposee"] = ""
        llm_result["statut"] = "qualification"
        llm_result["escalade_necessaire"] = False
        confidence = min(confidence, 0.50)

    has_solution = bool(llm_result.get("solution_proposee", "").strip())
    if has_solution and has_similar:
        confidence = max(confidence, 0.65)

    combined = round((confidence * 0.6) + (nlp_confidence * 0.4), 2)
    llm_result["confidence_score"] = combined

    if combined < 0.70 and not has_solution:
        missing_items = []
        if not llm_result.get("module") and not context.get("module"):
            missing_items.append("module exact")
        if not llm_result.get("type_incident") and not context.get("type_incident"):
            missing_items.append("type d'incident")
        missing_items.extend(
            [
                "message d'erreur exact",
                "etapes pour reproduire le probleme",
                "impact metier et caractere bloquant",
                "version du logiciel ou capture d'ecran",
            ]
        )
        deduped = []
        for item in missing_items:
            if item not in deduped:
                deduped.append(item)
        llm_result["infos_manquantes"] = "; ".join(deduped[:4])
        llm_result["resume_technicien"] = (
            f"Probleme client: {llm_result.get('probleme_resume', '')[:220]} | "
            f"Module probable: {llm_result.get('module') or context.get('module') or 'inconnu'} | "
            f"Type probable: {llm_result.get('type_incident') or context.get('type_incident') or 'inconnu'} | "
            f"Informations a recuperer: {llm_result['infos_manquantes']}"
        )
        llm_result["solution_proposee"] = ""
        llm_result["reponse"] = (
            "Je ne suis pas encore assez sur pour proposer une solution fiable. "
            "Merci de verifier que les informations affichees dans le resume sont correctes, puis de me donner : "
            f"{llm_result['infos_manquantes']}. "
            "Ensuite, votre ticket sera assigne a un technicien qui vous repondra le plus tot possible."
        )
        llm_result["statut"] = "qualification"

    if combined < 0.42:
        llm_result["escalade_necessaire"] = True
        llm_result["statut"] = "escalade_technique"

    if llm_result.get("niveau_urgence") == "critique":
        llm_result["escalade_necessaire"] = True
        llm_result["bloquant"] = True

    if not llm_result.get("module") and context.get("module"):
        llm_result["module"] = context["module"]
    if not llm_result.get("type_incident") and context.get("type_incident"):
        llm_result["type_incident"] = context["type_incident"]

    llm_result["metrics"] = {
        "nlp_confidence": round(nlp_confidence, 2),
        "llm_confidence": round(confidence, 2),
        "combined": combined,
        "had_similar": has_similar,
        "best_sim": round(best_similarity, 3),
    }
    return llm_result
