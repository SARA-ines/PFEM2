import { useState, useMemo } from "react";
import "./FonctionnalitesPicker.css";

const FONCTIONNALITES = {
  achats: [
    "Affectation DA","Agenda","Attandu Non Recu","Avoir Fournisseur",
    "Commande Fournisseur","Contrat","Demande de paiement","Demande d'achat",
    "Demande fond interne","Demande Prix","Dossier Import","Facture Charge",
    "Facture Fournisseur","Fiche Fournisseur","Gestion des Kits",
    "Paiement Fournisseur","Plafond Chiffre affaire","Service Fait","TCO",
  ],
  administration: [
    "Unités","Utilisateur","Jours Fériés","Membres admin",
    "Modèle de Jours Fériés","Week End","Activités","Actionnaires",
    "Circuit de validation","Dirigeants","Filiales",
    "Responsabilités et Permissions","Parametres Application",
    "Periode Comptable","Exercice","Groupe d'utilisateurs",
  ],
  budget: [
    "Analyse","Analyse Entreprise","Dépense engagée","Dépense prévue",
    "Engagements budgétaires","Prévision budgétaires","Postes budgétaires",
    "Poste Quantitatif","Réalisations budgétaires","Reservation",
    "NomenClature","Transfert Reliquat Emis","Transfert Reliquat Reçu",
  ],
  comptabilite: [
    "Rapprochement Bancaire/Ecritures","Fiche Tiers","Autre tiers",
    "Tiers Produit","Ecritures comptables","Param pièce",
    "Paramétrage clôture","Parametrage ecriture",
    "Pièces de Réouverture [N-1] => [N]","Interrogation des balances",
    "Pièces de Clôture [N]","Consolidation Comptabilité",
    "Demande fond interne","Interrogation des écritures",
    "Interrogation des soldes","Positionnement des VTRs",
    "Rapprochement des ecritures","Centre de Responsabilité",
    "Interface Comptabilité","Interface Comptabilité Paie","Journaux",
    "Comptes Globaux","Période Comptable","Période Modèle",
    "Comptes Comptables","Parametres Comptabilité",
    "Paramétrage des journaux","Paramétrage des tableaux PDF","G50",
    "Tableau Comptabilité Notes","Titres des états Comptabilité",
    "Liasse Fiscale - Bilan Fiscal (Actif)","Liasse Fiscale - Bilan Fiscal (Passif)",
    "Liasse Fiscale - Compte de Résultat","Liasse Fiscale - Détermination du résultat fiscal",
    "Etats Financiers - Bilan (Actif)","Etats Financiers - Bilan (Passif)",
    "Etats Financiers - Flux de Trésorerie","Etats Financiers - Variation des Capitaux Propres",
    "Annexe - Evolution des Immobilisations","Annexe - Tableau des Amortissements",
    "Annexe - Tableau des Provisions","Annexe - Etat des échéances",
  ],
  analytique: [
    "Ecritures comptables","Interrogation des balances","Interrogation des soldes",
    "Centre de Responsabilité","Journaux","Comptes Globaux","Comptes Comptables",
  ],
  facturation: [
    "Facture Client","Facture d'Avoir","Facture d'avoir libre",
    "Facture Retenue de Garantie","Bon de Livraison","Commande Client",
    "Proforma Client","Contrat Client","Demande offre client",
    "Paiement Client","Encaissement Bon Livraison","Bon chargement",
    "Service Fait","Fiche Client","Reclamation","Caution","Prevision",
  ],
  fiscalite: [
    "Déclaration des factures","Facture Fournisseur","Périodes fiscales",
    "Modèles Périodes fiscales","Facture Client",
  ],
  tresorerie: [
    "Type Mouvement","Validation demande de fond","Tiers employé",
    "Rapprochement Bancaire/Trésorerie","Caisse","Credit Bail",
    "Transfert de crédit","Demande de fond","Demande fond interne",
    "Demande de fond reçu","Demande de paiement","Credit Exploitation",
    "Interrogations trésorerie","Credit Invest","Ordre virement",
    "Ordre versement interne","Autres paiements bancaires",
    "Période Trésorerie","Modèle Période Trésorerie","Relevé Bancaire",
    "Chèques","Tous les mouvements","Changer état créance",
    "Dettes","Créances","Mouvement Tiers",
  ],
  paie: [
    "Charges Patronales par Caisses","Charges employés","Charges Patronales",
    "Interface Cacobatph","Caisses de cotisations","Clôturer une paie",
    "Consultation fiche employé","Droit de congé annuel","Employé",
    "Bulletin de paie","Bulletin de paie Simulation","Saisie des rappels",
    "Rappel changement de Cat/Sec/Ech","Rappel sur net","Rappel simple",
    "Colonnes Livre de paie","Saisie des rubriques","Grille des salaires",
    "Interface Comptabilité","Interface D.A.S","Intérogation des données",
    "Abattements IRG","Absences non prise dans l'IRG",
    "Rubriques non prise dans le base seuil exo IRG",
    "Journal par rubrique","Livre de paie","Types de paie","Vider les variables",
    "Virement bancaire sur fichier Texte","Virement CCP sur fichier Texte",
    "Ordre des rubriques","Période Paie","Prêts",
    "Provision indemnité de fin de carrière",
    "Paramétrage virement bancaire","Paramétrage virement CCP",
    "Rappel changement de poste","Paie rétroactive","Rubriques de paie",
    "Saisie globale","Tableaux de calcul","Titre de congé annuel",
  ],
  rh: [
    "PV de suspension","PV d'audition","PV de commission",
    "PV de commission de recours","PV d'incidence","Controle Medicale",
    "Visite Embauche","Visite Periodique","Piece Maitresses","Rendez-vous",
    "Sélection des candidatures internes","Accident de travail",
    "Intérogation des données RH","Dotations Employes","Liste des entretiens",
    "Personnel","Demandes","Demandes d'absence","Demandes de congé",
    "Demandes de dotation","Demandes de formation",
    "Demandes de mise en disponibilité","Demandes de mission",
    "Demandes de mutation","Demandes de promotion/rétrogradation",
    "Demandes de prêt","Demandes de recours sur mesure disciplinaire",
    "Demandes de recrutement","Demandes de réintégration",
    "Demandes de dépot de dossier de retraite","Demandes de sanction",
    "Consultation fiche personnel","Audiences","Liste des besoins",
    "Evaluation","EvaluationEntreprise","Expériences",
    "Affectation des documents","Liste des candidatures","CV Catégorie",
    "Modèles des documents","Paramètres des documents","Contrats","Sanctions",
    "PV d'installation","Appréciation","Plans de Formation","Action de formation",
    "Sessions Formation","Diplômes","Diplômes employé","Périodes de formation",
    "Ordres Mission","Frais de mission","Barème frais mission",
    "Mouvements","Mutation","Dossier de retraite","Départs","Entrées",
    "Filiere","Compétences","Postes","Catégorie Socioprofessionnelle",
    "Nature Sanction","Commission de sanction",
  ],
  gestion_temps: [
    "Exportation BIGGT","Arrêt de travail","Interface Big GT",
    "Nature Congé","HeuresSup","Droit Congé","Absences",
    "Types Absence","Titre de Congé",
  ],
  stock: [
    "Sortie Kit","Stock Article","Sortie stock","Demande fond interne",
    "Réception","Stock Archive","Gestion des Kits","Transfert Magasin",
    "Ajustement","Fiche Article","Entree stock","Demande Interne",
    "Cacher la valorisation","Inventaire","Gestion des Produits",
    "Bon de Réservation","Retour entree","Retour Production",
    "Retour sortie","Mouvement N°Serie","Modifier Libelle Article",
    "Modifier prix Production","Mouvement Stock","Cloturer stock par période",
  ],
  ventes: [
    "Changement transport","Modifier Prix de Gestion des ventes",
    "Remise Demande offre","Retour Garantie","Proforma Client",
    "Contrat Client","Demande offre client","Facture d'Avoir",
    "Facture d'avoir libre","Facture Client","Service Fait",
    "Modifier Franchise","Facture Retenue de Garantie","Confirmer livraison",
    "Livraison en préparation","Bon de Livraison","Analyse Offre",
    "Retour Livraison","Retour sans Livraison","Commande Client",
    "Paiement Client","Encaissement Bon Livraison","Bon chargement",
    "Saisie factures dépassant le seuil","Fiche Client","Demande fond interne",
    "Agenda","Caution","Prevision","Reclamation","Gestion des Kits","Location",
  ],
  sav: [
    "Commande pieces de rechanges","Rapport","Ordre d'intervention",
    "Materiels vendus","SavDevis","Accuse reception materiel a reparer",
    "Article garantie","Atelier","Bon de sortie","Liste des gammes",
    "Metier","Liste des operations","Contrat reparation",
    "Demande assistance","Demande expertise","Devis","Demande garantie",
    "Diagnostic","Demande reparation","Numero de serie non livree",
    "Intervenant","Mise en route","NaturePanne","Outillage",
    "Pause garantie","Planning des visites","Reclamations clients",
    "Reconnaissance de fourniture","TypePanne",
  ],
  crm: [
    "Activité/tache","Affaire","Cause","Collaborateur","Compagne",
    "Contact","Devis","Lead","Prospect","Statut Prospect","Type Compagne",
  ],
  marches: [
    "Modele Document","Parametre Document","Appel Offres",
    "Attribution Provisoire","Cahier des charges","Criteres",
    "Demande d'éclaircissement","Plis","Projets","Commission",
    "Consultation","Decision","Dossier","ODS","Personnel","Recours",
    "Seance","Soumission","Structure","Type Appel Offre","Retrait CDC",
  ],
  gpao: [
    "Plan Industriel Commercial","Liste A Servire","CBN Composants",
    "CBN Matières","Composants","Matieres","Operations","Douchette",
    "Details Pointage Centre Charge","Details Pointage Matieres et Fournitures",
    "Pointage Entrée / Sortie","Gamme Produit","Composant","Fourniture",
    "Equipement","Non Conformité","Calcul besoin net","Simulation","Colisage",
    "Famille Instruments de Mesure","Groupement de ressources",
    "Instruments de Mesure","Qualification","Centre de charge","Machine",
    "Ordre de production","Cloture","Interruption","Lancement","Personnel",
    "Plan","Prevision","Produit","Stock Théorique Production",
    "Situation Centre De Charges","Temps Non Affécté",
  ],
  qualite: [
    "StNC","TNC","VolP","Statut","Type","CNC","DNC","ENC","GNC","ONC",
    "Gestion des supports de document","Dossier","QNCFC","Fiche Document",
    "Gestion des causes d'évolution","Gestion des types de document",
    "Action Qualité","Demande Action Qualité","Statut AQ","Type AQ",
    "Controle et decision","Decision","Echantillon",
    "Controle reception fournisseur","Controle sur retour client",
    "Gestion des défauts","Gestion des contrôles articles",
    "Controle sur FCA","Controle sur OF","Gestion des résultats","Indicateurs",
    "Origine de controle","Cause NC","Decision NC","Efficacite NC",
    "Gravite NC","Origine NC","Processus NC","Statut NC","Type NC",
    "NonConformite","Relevé OF","Type de controle",
  ],
  gestion_projets: [
    "Demande Avance sur Approvisionnement","Attribution définitive",
    "Attribution provisoire","Appel Offres","Catalogue Lots/Articles",
    "Criteres","Exigences","Marche","Recours","Retrait Cahier des charges",
    "Type Consultation","Type appel d'offre","Main levée","Attachements",
    "ODS","Paiement","Demande Avance Forfaitaire","Structure projets",
    "Situation","Caution","Parametrage projets",
  ],
  gestion_taches: [
    "Tâche","Attachement PVI","Categories des ressources","Planification",
    "Réalisation","Ressource","Paramétrage des Tâches",
  ],
  immobilisations: [
    "Reformes","Retour sortie temporaire","Inventaire Immobilisations",
    "Motif Sortie","Mouvement","Police assurance","Perte",
    "Immobilisations en cours","Modification du plan d'amortissement",
    "Classement","Fiche Immobilisation (Volet comptable)",
    "Preparation Reforme","Utilisateur immobilisation","Reevaluation",
    "Liaison des comptes","Familles d'immobilisations","Fiche immobilisation",
    "Donnation","Destructions","Nature Assurance","Amortissement",
    "Andi","Assurance Agence","Affectations","Cession",
    "Transfert entrant","Transfert Sortant",
  ],
  gestion_documents: [
    "Emplacement","Dossier","Document","Classeur","ClasseParam","DocParam",
  ],
};

export default function FonctionnalitesPicker({ module, value, onChange }) {
  const [search, setSearch] = useState("");

  const selected = useMemo(
    () => (value ? value.split(",").map((s) => s.trim()).filter(Boolean) : []),
    [value]
  );

  const available = useMemo(() => {
    const list = FONCTIONNALITES[module] || [];
    if (!search.trim()) return list;
    const q = search.toLowerCase();
    return list.filter((f) => f.toLowerCase().includes(q));
  }, [module, search]);

  const hasOptions = (FONCTIONNALITES[module] || []).length > 0;

  function toggle(fonc) {
    const next = selected.includes(fonc)
      ? selected.filter((s) => s !== fonc)
      : [...selected, fonc];
    onChange(next.join(", "));
  }

  function remove(fonc) {
    onChange(selected.filter((s) => s !== fonc).join(", "));
  }

  if (!module) {
    return (
      <p className="fonc-empty">Choisissez d'abord un module pour voir les fonctionnalités disponibles.</p>
    );
  }

  if (!hasOptions) {
    return (
      <p className="fonc-empty">Aucune fonctionnalité prédéfinie pour ce module. Décrivez-les dans la description.</p>
    );
  }

  return (
    <div className="fonc-picker">
      {selected.length > 0 && (
        <div className="fonc-selected">
          {selected.map((f) => (
            <span key={f} className="fonc-chip fonc-chip--selected">
              {f}
              <button type="button" className="fonc-chip-remove" onClick={() => remove(f)} aria-label={`Retirer ${f}`}>×</button>
            </span>
          ))}
        </div>
      )}

      <input
        className="fonc-search"
        type="text"
        placeholder="Rechercher une fonctionnalité..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="fonc-list">
        {available.length === 0 ? (
          <p className="fonc-empty">Aucun résultat pour « {search} »</p>
        ) : (
          available.map((f) => {
            const checked = selected.includes(f);
            return (
              <label key={f} className={`fonc-item${checked ? " fonc-item--checked" : ""}`}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggle(f)}
                />
                <span>{f}</span>
              </label>
            );
          })
        )}
      </div>

      {selected.length > 0 && (
        <p className="fonc-count">{selected.length} fonctionnalité(s) sélectionnée(s)</p>
      )}
    </div>
  );
}
