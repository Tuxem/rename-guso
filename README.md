# GUSO Contract Processor

🇫🇷 **Processeur de contrats GUSO** (Déclaration Unique et Simplifiée)

Un script Python robuste pour automatiser le traitement des contrats GUSO : extraction de données, renommage standardisé et génération de rapports détaillés.

---

## 📋 Fonctionnalités

- ✅ **Extraction automatique** des données depuis les PDFs (dates, lieux, heures, salaires)
- ✅ **Support multi-format** (v1 et v2 des contrats GUSO)
- ✅ **Renommage standardisé** : `YYYYMMDD - Lieu - HH.pdf`
- ✅ **Export CSV** avec toutes les données extraites
- ✅ **Mode dry-run** pour prévisualiser les changements
- ✅ **Système de sauvegarde** avec argument `--backup`
- ✅ **Gestion d'erreurs robuste** avec validation des données
- ✅ **Logging détaillé** (console et fichier)
- ✅ **Calcul automatique** des heures totales et salaires

---

## 🚀 Installation

### Prérequis

- Python 3.7+
- pip

### Installation des dépendances

```bash
pip install PyMuPDF
```

---

## 💻 Utilisation

### Syntaxe de base

```bash
python rename-guso.py <dossier_année> [options]
```

### Exemples

#### Traitement simple
```bash
python rename-guso.py 2023
```

#### Prévisualisation sans modification (dry-run)
```bash
python rename-guso.py 2023 --dry-run
```

#### Avec sauvegarde des fichiers originaux
```bash
python rename-guso.py 2023 --backup
```

#### Export des données vers CSV
```bash
python rename-guso.py 2023 --output summary.csv
```

#### Combinaison backup + CSV + logging détaillé
```bash
python rename-guso.py 2023 --backup --output 2023_contrats.csv --log-level DEBUG --log-file process.log
```

---

## ⚙️ Options

| Option | Description |
|--------|-------------|
| `year_folder` | **[REQUIS]** Chemin vers le dossier contenant les PDFs (ex: "2023") |
| `--dry-run` | Prévisualiser les changements sans modifier les fichiers |
| `--backup` | Créer des copies de sauvegarde avant renommage (dans `backup/`) |
| `--output FILE` ou `-o FILE` | Exporter les données vers un fichier CSV |
| `--log-level LEVEL` | Niveau de log : `DEBUG`, `INFO`, `WARNING`, `ERROR` (défaut: `INFO`) |
| `--log-file FILE` | Sauvegarder les logs dans un fichier |

---

## 📊 Format de sortie

### Renommage des fichiers

Les fichiers sont renommés selon le format :

```
YYYYMMDD - Lieu - HH.pdf
```

**Exemple :**
```
20231115 - Paris - 8H.pdf
20231220 - Lyon - 12H.pdf
```

### Export CSV

Le fichier CSV contient les colonnes suivantes :

| Colonne | Description |
|---------|-------------|
| `status` | Statut du traitement (`success`, `skipped`, `error`) |
| `original_filename` | Nom original du fichier |
| `new_filename` | Nouveau nom du fichier |
| `format_version` | Version du format GUSO (`v1` ou `v2`) |
| `begin_date` | Date de début du contrat |
| `end_date` | Date de fin du contrat |
| `place` | Lieu de l'événement |
| `event` | Nom de l'événement |
| `hours` | Nombre d'heures |
| `salary_brut` | Salaire brut (€) |
| `salary_net` | Salaire net (€) |
| `secu` | Numéro de sécurité sociale |
| `error_message` | Message d'erreur (si applicable) |

### Résumé console

Le script affiche un résumé détaillé :

```
======================================================================
📊 PROCESSING SUMMARY
======================================================================
Total contracts:          25
  ✓ Successfully processed: 20
  ⊘ Skipped (already done): 3
  ✗ Errors:                 2
----------------------------------------------------------------------
Total hours:              180H
Total hours (no SHELTER): 165H
----------------------------------------------------------------------
Total salary (brut):      2450.00€
Total salary (net):       2100.00€
======================================================================
```

---

## 🛡️ Gestion des erreurs

Le script gère automatiquement :

- ❌ PDFs corrompus ou vides
- ❌ Formats de date invalides
- ❌ Données manquantes ou incomplètes
- ❌ Problèmes de permissions fichiers

En cas d'erreur :
- Le fichier problématique est **ignoré** (pas de renommage)
- L'erreur est **loggée** avec détails
- Le traitement **continue** pour les autres fichiers
- Le résumé final liste tous les fichiers en erreur

---

## 🔧 Fonctionnement technique

### Détection de format

Le script détecte automatiquement la version du contrat GUSO :
- **v2** : Présence du titre "Déclaration unique et simplifiée" à des coordonnées spécifiques
- **v1** : Format ancien (par défaut si v2 non détecté)

### Extraction de données

Les données sont extraites via des coordonnées PDF précises :
- Coordonnées **v2** : définies dans `V2_COORDS`
- Coordonnées **v1** : définies dans `V1_COORDS`

### Validation

Avant renommage, le script valide :
- ✅ Présence de la date de début
- ✅ Présence du lieu
- ✅ Format de date valide (DD/MM/YYYY)
- ✅ Heures > 0

---

## 📁 Structure du projet

```
rename-guso/
├── rename-guso.py     # Script principal
├── README.md          # Cette documentation
└── 2023/              # Exemple de dossier d'année
    ├── contract1.pdf
    ├── contract2.pdf
    └── backup/        # Créé automatiquement avec --backup
        ├── contract1.pdf
        └── contract2.pdf
```

---

## 🐛 Bugs corrigés

Les bugs suivants ont été corrigés dans cette version :

1. ✅ **Crash sur noms de fichiers courts** : Protection contre `split()[3]` sur noms sans 4 parties
2. ✅ **end_date non utilisée** : Extraction et export de la date de fin (format v1)
3. ✅ **Valeur par défaut "8H"** : Maintenant configurable via `DEFAULT_HOURS_V1`
4. ✅ **Calcul heures "no_shelter"** : Corrigé pour tous les contrats (pas seulement renommés)
5. ✅ **Code de debug** : Suppression de `pdb.set_trace()` en production

---

## 🚦 Workflow recommandé

### 1. Prévisualisation (Dry-run)

```bash
python rename-guso.py 2023 --dry-run
```

Vérifiez que les renommages sont corrects.

### 2. Traitement avec backup

```bash
python rename-guso.py 2023 --backup --output 2023_summary.csv
```

Les fichiers originaux sont sauvegardés dans `2023/backup/`.

### 3. Vérification

- Consultez le résumé console
- Ouvrez `2023_summary.csv` pour vérifier les données
- Vérifiez que les heures totales correspondent

### 4. En cas de problème

Si un renommage est incorrect :
- Les originaux sont dans `2023/backup/`
- Restaurez avec : `cp backup/* .`
- Corrigez et relancez

---

## 📝 Notes

- Les fichiers déjà renommés (format `20YYMMDD - ...`) sont **automatiquement ignorés**
- L'extraction fonctionne mieux avec des PDFs **natifs** (pas des scans)
- Les coordonnées PDF peuvent nécessiter un ajustement selon la version exacte du template GUSO
- Les caractères spéciaux dans les noms de lieux (`/`, `\`) sont remplacés par `-`

---

## 🤝 Contribution

Pour signaler un bug ou proposer une amélioration :
1. Vérifiez les logs avec `--log-level DEBUG`
2. Notez le message d'erreur exact
3. Conservez le PDF problématique pour analyse

---

## 📄 Licence

Ce script est fourni tel quel, sans garantie. Utilisez-le à vos propres risques.

---

## 🔗 Liens utiles

- [PyMuPDF Documentation](https://pymupdf.readthedocs.io/)
- [Python argparse](https://docs.python.org/3/library/argparse.html)
- [Python csv](https://docs.python.org/3/library/csv.html)

---

**Version:** 2.0
**Dernière mise à jour:** 2025-11-15
