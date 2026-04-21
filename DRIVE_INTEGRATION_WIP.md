# Drive integration — état du WIP

Document de reprise de contexte pour la branche `drive-integration`.

Branche : `drive-integration`
Base : `main` (`9bdb551` — "design revamp")
Commits sur la branche : **1** seul commit de travail

```
1c537eb (fullstack) add drive integration WIP
```

Tout ce qui suit décrit l'intégralité du delta `main..HEAD`.

---

## 1. Objectif

Permettre à un agent qui utilise La Suite de joindre à un transfert des fichiers déjà stockés dans **Drive** (La Suite), sans devoir les re-télécharger localement puis les re-déposer.

Le bouton "Joindre depuis Drive" n'apparaît que si l'instance est explicitement opt-in (`DRIVE_BASE_URL` défini). Instances publiques sans Drive associée : aucun changement visible.

---

## 2. Décision d'architecture : hard copy (pas de référence)

Modèle retenu : **hard copy**. Quand l'utilisateur choisit un fichier dans Drive, on :

1. Ouvre le picker Drive via `@gouvfr-lasuite/drive-sdk`.
2. Télécharge les octets du fichier côté navigateur (`fetch(item.url, { credentials: "include" })`, avec le cookie de session Drive de l'agent).
3. Emballe chaque blob dans un `File` et le passe exactement dans le même flux multipart que les fichiers uploadés localement.

Le fichier vit donc **en double** : dans Drive ET dans S3 Transferts. Aucune référence au document Drive n'est persistée côté Transferts.

**Pourquoi pas un modèle "référence"** (on ne stocke que l'URL Drive, on redirige au download) :
- Les TTL de Drive et Transferts ne coïncident pas — un transfert pourrait promettre "valable 30 jours" alors que le doc Drive a bougé/été supprimé entre-temps.
- Les destinataires d'un lien Transferts n'ont en général pas de compte Drive. Pas d'URL téléchargeable non-authentifiée exposée par Drive aujourd'hui.
- Drive n'expose pas d'URL de download signée "scoped + anonyme" à ce jour.

Cette décision est documentée dans le header de `DriveAttachButton.tsx`. Si un jour un mode "référence" est ajouté, il devra coexister comme seconde action, **ne pas remplacer** le hard copy.

---

## 3. Changements backend

### 3.1 `src/backend/transferts/settings.py`

Ajout d'un dict `DRIVE_CONFIG` sur `Base` :

```python
DRIVE_CONFIG = {
    "base_url": os.environ.get("DRIVE_BASE_URL", ""),
    "sdk_url":  os.environ.get("DRIVE_SDK_URL",  "/sdk"),
    "api_url":  os.environ.get("DRIVE_API_URL",  "/api/v1.0"),
    "app_name": os.environ.get("DRIVE_APP_NAME", "Drive"),
}
```

**Piège** : on utilise `os.environ.get` directement, **pas** `values.Value(...)`. `django-configurations` ne résout `values.Value` que pour les attributs de classe top-level, pas les valeurs imbriquées dans un dict littéral. Garder tel quel.

`sdk_url` et `api_url` sont relatifs par défaut (`/sdk`, `/api/v1.0`) : ils sont joints au `base_url` côté frontend via `joinUrl()`. On peut les overrider avec des URL absolues si on veut pointer vers un host différent.

### 3.2 `src/backend/core/api/viewsets/config.py` (`ConfigView`)

Le endpoint public `GET /api/v1.0/config/` ajoute conditionnellement une clé `DRIVE` dans son payload :

```python
drive_config = getattr(settings, "DRIVE_CONFIG", None) or {}
if drive_config.get("base_url"):
    payload["DRIVE"] = {
        "base_url": drive_config["base_url"],
        "sdk_url":  drive_config.get("sdk_url", "/sdk"),
        "api_url":  drive_config.get("api_url", "/api/v1.0"),
        "app_name": drive_config.get("app_name", "Drive"),
    }
```

**Principe** : si `DRIVE_BASE_URL` est vide, la clé `DRIVE` est **absente** de la réponse. Le frontend teste `config.DRIVE` avant de rendre le bouton, donc la feature est invisible sur les instances non opt-in.

### 3.3 `env.d/development/backend.defaults`

Ajout d'un block commenté pour la conf dev :

```
DRIVE_BASE_URL=
```

Le commentaire rappelle aussi la contrainte CORS côté Drive (cf. §6).

**À noter** : il n'y a **pas** eu de modif de modèle/migration/viewset/serializer backend pour Drive. Certaines tâches (Drive — modèle + migration, serializers + viewset, endpoint unlock, page download dédiée Drive, etc.) étaient dans le plan initial mais ont été abandonnées au profit de l'approche hard-copy pure, qui ne requiert aucune persistence spécifique côté Transferts.

---

## 4. Changements frontend

### 4.1 Dépendances ajoutées (`src/frontend/package.json`)

```json
"@gouvfr-lasuite/cunningham-react": "4.2.0",   // déjà présent, juste réordonné
"@gouvfr-lasuite/drive-sdk": "^0.0.2"          // nouveau
```

Le `package-lock.json` a été régénéré en entier (gros diff, pas d'intérêt à le lire ligne à ligne).

### 4.2 `src/frontend/src/features/providers/config.tsx`

Extension du type `AppConfig` :

```ts
export interface DriveConfig {
  base_url: string;
  sdk_url: string;
  api_url: string;
  app_name: string;
}

export interface AppConfig {
  // ...
  DRIVE?: DriveConfig;   // undefined quand l'instance n'est pas opt-in
}
```

### 4.3 `src/frontend/src/features/transfers/components/DriveAttachButton.tsx` (**nouveau**)

Composant unique qui fait tout le travail Drive côté UI.

API :
```ts
interface Props {
  onPick: (files: File[]) => void;      // files Drive convertis en File
  onError?: (message: string) => void;  // erreur user-facing traduite
  disabled?: boolean;
  maxFileSize?: number;                 // garde pré-download
}
```

Flow interne :
1. **Short-circuit** : si `config.DRIVE` est absent, le composant rend `null`. C'est la double-garde (le parent ne le monte déjà que dans ce cas).
2. **Click** → `openPicker({ url, apiUrl })` depuis `@gouvfr-lasuite/drive-sdk`. Les URL sont construites via `joinUrl(base, path)` qui gère correctement absolu/relatif/slash finaux.
3. **Garde de taille** : si un item dépasse `maxFileSize`, on abort **avant** de télécharger les octets. Évite de transférer 20 GiB pour les jeter au merge-check de `TransferForm`.
4. **Download séquentiel** des items : `for (const item of result.items)` avec `await fetch(item.url, { credentials: "include" })`. Séquentiel = cap à ~1 blob résident en RAM. Critique pour ne pas OOM l'onglet sur plusieurs gros fichiers.
5. `credentials: "include"` est **obligatoire** — `item.url` pointe vers la route media authentifiée de Drive, pas une URL S3 pré-signée.
6. Chaque blob → `new File([blob], item.title, { type: blob.type || "application/octet-stream" })`.
7. `onPick(files)` final. Fail-case unique : même message i18n user-facing ("Could not download from {{app}}…").

État local minimal : un seul `busy: boolean`. Icône `hourglass_empty` pendant le download, `folder_open` sinon. Label change ("Attach from …" → "Downloading from …").

### 4.4 `src/frontend/src/features/transfers/components/FileDropZone.tsx`

Nouvelle prop `extraCta?: ReactNode`.

Contraintes d'intégration :
- Le slot est rendu **uniquement quand aucun drag n'est actif** (`!isDragActive`) — on garde l'état "relâche pour uploader" propre.
- `onClick` du wrapper fait `e.stopPropagation()` pour que le bouton embarqué ne déclenche pas le file picker natif du dropzone.
- Le parent `.file-dropzone__cta` a `pointer-events: none` pour que tout le fond reste cliquable ; `__extra` re-active `pointer-events: auto` localement.

```tsx
{extraCta && !isDragActive && (
  <div className="file-dropzone__extra" onClick={(e) => e.stopPropagation()}>
    <span className="file-dropzone__separator">{t("or")}</span>
    {extraCta}
  </div>
)}
```

### 4.5 `src/frontend/src/features/transfers/components/TransferForm.tsx`

Deux points d'insertion du bouton Drive :

**A. Avant qu'aucun fichier ne soit ajouté** — via le slot `extraCta` du dropzone :
```tsx
<FileDropZone
  files={files}
  onChange={handleFilesChange}
  extraCta={config.DRIVE ? (
    <DriveAttachButton
      onPick={handleFilesChange}
      onError={setFileError}
      disabled={busy}
      maxFileSize={config.TRANSFER_MAX_FILE_SIZE}
    />
  ) : undefined}
/>
```

**B. Après ajout d'au moins un fichier** — dans une barre d'actions qui contient déjà le bouton "Ajouter un élément" :
```tsx
<div className="transfer-form__add-actions">
  <button className="transfer-form__add-item" …>Ajouter…</button>
  {config.DRIVE && <DriveAttachButton … />}
</div>
```

Dans les deux cas `handleFilesChange` est le même callback qui *merge* les fichiers et re-check les limites agrégées.

### 4.6 `src/frontend/src/features/transfers/components/_transfers.scss`

- `.transfer-form__add-actions` : flex row avec gap pour aligner "Ajouter un élément" et "Joindre depuis Drive".
- `.file-dropzone__extra` : flex column centré avec `pointer-events: auto`.
- `.file-dropzone__separator` : le petit "ou" en gris sous la zone principale.

### 4.7 i18n — `public/locales/common/{fr-FR,en-US,nl-NL}.json`

Quatre nouvelles clés, traduites dans **les trois** locales :

| Clé | fr-FR | en-US | nl-NL |
|---|---|---|---|
| `or` | "ou" | "or" | "of" |
| `Attach from {{app}}` | "Joindre depuis {{app}}" | "Attach from {{app}}" | "Toevoegen vanuit {{app}}" |
| `Downloading from {{app}}...` | "Téléchargement depuis {{app}}…" | "Downloading from {{app}}..." | "Downloaden vanuit {{app}}…" |
| `Could not download from {{app}}. Check that the file is accessible and try again.` | "Impossible de télécharger depuis {{app}}. Vérifiez que le fichier est accessible et réessayez." | idem EN | "Downloaden vanuit {{app}} is mislukt. Controleer of het bestand toegankelijk is en probeer opnieuw." |

`{{app}}` est substitué par `config.DRIVE.app_name` (par défaut "Drive").

---

## 5. Comment tester en local

### 5.1 Côté Transferts

Dans `env.d/development/backend.defaults` (ou équivalent), définir :

```
DRIVE_BASE_URL=https://drive.dev.lasuite.numerique.gouv.fr
```

Redémarrer le backend. Le `/api/v1.0/config/` doit alors exposer la clé `DRIVE`. Vérifiable :

```bash
curl -s http://localhost:8071/api/v1.0/config/ | jq .DRIVE
```

### 5.2 Côté Drive

Il faut que l'instance Drive visée accepte l'origine Transferts en CORS **avec credentials** :
- Ajouter l'origine Transferts à **`CORS_ALLOWED_ORIGINS`** (pour l'API) **et** à **`SDK_CORS_ALLOWED_ORIGINS`** (pour le canal SDK postMessage).
- Conserver `CORS_ALLOW_CREDENTIALS=True`.

Sans ça : le `fetch(item.url, { credentials: "include" })` échouera silencieusement côté navigateur (CORS bloqué) et l'utilisateur verra le message "Impossible de télécharger depuis Drive…".

### 5.3 Golden path

1. Se connecter à Drive dans un autre onglet (cookie de session posé).
2. Ouvrir Transferts → page création transfert.
3. Bouton "Joindre depuis Drive" visible sous le dropzone.
4. Click → picker Drive s'ouvre en modal/popup.
5. Sélectionner un ou plusieurs fichiers → picker se ferme.
6. Le bouton passe en "Téléchargement depuis Drive…" (icône sablier).
7. Les fichiers apparaissent dans la liste du formulaire Transferts avec leur taille.
8. Submit → upload multipart habituel vers S3 Transferts.

### 5.4 Edge cases à vérifier

- Instance sans `DRIVE_BASE_URL` → aucun bouton visible. ✅
- Fichier > `TRANSFER_MAX_FILE_SIZE` → erreur avant download. ✅
- CORS manquant / cookie Drive absent → erreur générique traduite. ✅
- Plusieurs fichiers sélectionnés → download séquentiel (regarder l'onglet Network, un fetch à la fois).
- Picker annulé (`result.type !== "picked"`) → no-op silencieux, `busy` remis à false.

---

## 6. Contraintes de déploiement (résumé pour ops)

Côté Transferts (instance A) :
```
DRIVE_BASE_URL=https://drive.B.example.gouv.fr
# Optionnels (par défaut OK si Drive a une topologie standard) :
# DRIVE_SDK_URL=/sdk
# DRIVE_API_URL=/api/v1.0
# DRIVE_APP_NAME=Drive
```

Côté Drive (instance B) :
```
CORS_ALLOWED_ORIGINS=[..., "https://transferts.A.example.gouv.fr"]
SDK_CORS_ALLOWED_ORIGINS=[..., "https://transferts.A.example.gouv.fr"]
CORS_ALLOW_CREDENTIALS=True
```

**Les deux listes CORS sont nécessaires**. Elles couvrent des canaux distincts :
- `CORS_ALLOWED_ORIGINS` : le `fetch` HTTP vers `item.url` (route media authentifiée).
- `SDK_CORS_ALLOWED_ORIGINS` : le canal `postMessage` entre la fenêtre du picker et Transferts.

---

## 7. Ce qui reste TODO (pourquoi c'est WIP)

Le commit est taggé WIP — points à clarifier/finir avant de proposer la PR :

1. **Tests d'intégration e2e** : rien de nouveau n'a été ajouté. Le flow repose sur le SDK Drive et sur le cookie de session — difficile à mocker utilement. Sans doute un test Playwright avec une vraie instance Drive de CI.
2. **Test manuel complet avec une vraie Drive dev** : à faire avec `drive.dev.lasuite.numerique.gouv.fr` (ou équivalent) pour valider CORS + flow réel. L'intégration n'a pour l'instant été validée que localement avec mocks.
3. **Gestion d'erreur par item** : le `try/catch` actuel englobe tout le lot. Si le 2e fichier sur 3 échoue, on perd aussi les 2 autres déjà téléchargés. À envisager : accumulator + rapport partiel ("2/3 fichiers joints, 1 a échoué").
4. **UX du "disabled"** : pendant le download Drive, on désactive `busy` mais le bouton "Ajouter un élément" voisin reste actif — on peut donc mélanger les deux flows. À tester, probablement inoffensif mais à confirmer.
5. **Icône sablier** : `hourglass_empty` est un placeholder. Le design system a peut-être un spinner plus adapté à valider avec le design.
6. **Validation du SDK version 0.0.2** : c'est une version pré-release. Vérifier avec l'équipe Drive s'il y a une version plus stable ou un contrat d'API à surveiller.
7. **Documentation utilisateur / admin** : rien dans `docs/` — à ajouter si on garde l'intégration. Contraintes CORS surtout.

Les tâches liées Drive déjà closes (voir liste des tasks) couvrent la partie qu'on a réellement faite. Les tâches "modèle + migration", "serializers + viewset backend", "page download" ont été fermées **sans code** car l'approche hard-copy les a rendues inutiles — pas d'oubli à reprendre.

---

## 8. Fichiers modifiés — récap

```
env.d/development/backend.defaults                                    +7
src/backend/core/api/viewsets/config.py                              +22 -10
src/backend/transferts/settings.py                                   +14
src/frontend/package.json                                            +2 -1
src/frontend/package-lock.json                                       (régénéré)
src/frontend/public/locales/common/{en-US,fr-FR,nl-NL}.json          +4 each
src/frontend/src/features/providers/config.tsx                       +9
src/frontend/src/features/transfers/components/
  DriveAttachButton.tsx                                              +117 (nouveau)
  FileDropZone.tsx                                                   +16 -2
  TransferForm.tsx                                                   +32 -12
  _transfers.scss                                                    +25
```

---

## 9. Notes diverses

- Le dossier `.drive/` à la racine est **untracked** et ignoré — c'est un clone de référence du projet Drive pour consulter le code du SDK. Ne pas l'ajouter au repo.
- La feature password a été retirée en amont sur `main` (commit `852893c`) — aucune interaction avec Drive.
- Le design revamp (`9bdb551`) est la base directe de cette branche, donc toute la stack SCSS/Cunningham 4 est déjà en place.
