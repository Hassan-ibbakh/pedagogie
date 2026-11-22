# Classe Claire

Application FastAPI de préparation pédagogique, avec recherche RAG dans Pinecone et génération via une API compatible OpenAI.

## Démarrage local

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Renseignez les clés directement dans `.env`. Ne publiez jamais ce fichier. Créez un index Pinecone utilisant le modèle d'embedding configuré, avec une dimension de **1536** pour `text-embedding-3-small` et la métrique cosine.

```powershell
uvicorn main:app --reload
```

L'assistant est accessible à `/assistant`. Il filtre les passages Pinecone selon les champs `level` et `subject`. Les réponses sans passages pertinents sont indiquées comme propositions générales et ne prétendent pas vérifier le programme officiel.

## Indexer les ressources

Préparez un fichier UTF-8 JSONL, avec un objet JSON par ligne. `text`, `level`, `subject` et `source` sont obligatoires. `page`, `chapter` et `resource_type` sont facultatifs.

```json
{"text":"Texte extrait de votre ressource pédagogique.","level":"CP","subject":"Mathématiques","source":"Nom du document","page":12,"chapter":"Nombres","resource_type":"cours"}
```

Les niveaux acceptés sont `CP`, `CE1`, `CE2`, `CM1`, `CM2` et `6ème`. Les matières acceptées sont `Arabe`, `Français` et `Mathématiques`.

Dans l'assistant, l'enseignant choisit d'abord le niveau, puis la matière. Il peut charger des PDF avec texte, DOCX ou TXT, jusqu'à 4 Mo par envoi. Les PDF scannés sans couche texte nécessitent une étape OCR et ne sont pas indexés. Les fichiers originaux ne sont pas conservés : seuls les fragments extraits et leurs embeddings sont envoyés à Pinecone dans un namespace propre à la session. Le bouton « Effacer les ressources » supprime ce namespace. Les prompts prédéfinis sont des modèles dans le code ; aucune base de données de prompts n'est requise.

```powershell
python -m rag.ingest .\documents.jsonl
```

L'indexation découpe les textes en fragments avec chevauchement, crée leurs embeddings et envoie les métadonnées à Pinecone par lots. Seules les ressources pour lesquelles vous disposez des droits d'utilisation doivent être indexées.

## Variables d'environnement

Voir `.env.example` pour la liste complète. `OPENAI_API_KEY`, `PINECONE_API_KEY` et `PINECONE_INDEX_NAME` sont nécessaires au chat. `OPENAI_BASE_URL` est facultatif pour les fournisseurs compatibles. Le nom du modèle, le namespace et le nombre de résultats (`RAG_TOP_K`, entre 1 et 10) sont configurables.

### Conversations persistantes avec Redis

Créez une base Redis Upstash et renseignez `UPSTASH_REDIS_REST_URL` et `UPSTASH_REDIS_REST_TOKEN` dans `.env`, puis dans les variables d’environnement du projet Vercel. Les conversations sont enregistrées côté serveur avec leur contexte, leurs messages et leurs références. Leur expiration est glissante, de 7 jours par défaut ; `CONVERSATION_TTL_SECONDS` peut être réglé entre 60 secondes et 30 jours. Chaque conversation peut aussi être effacée depuis l’interface. L’identifiant conservé dans le navigateur ne contient aucune clé Redis.

Le plan gratuit Upstash indique actuellement 250 Mo et 500 000 commandes mensuelles ; consultez les quotas en vigueur selon l’usage prévu.

### Conversations persistantes

La page Assistant conserve les messages, le contexte pédagogique et les références dans Upstash Redis. Chaque conversation a un identifiant aléatoire conservé dans le navigateur et une durée de vie glissante de 7 jours par défaut (`CONVERSATION_TTL_SECONDS`, maximum 30 jours). Les données expirent automatiquement ; l'enseignant peut aussi effacer une conversation depuis l'interface.

Créez une base Redis Upstash, puis définissez `UPSTASH_REDIS_REST_URL` et `UPSTASH_REDIS_REST_TOKEN` dans `.env` pour le développement local et dans les variables du projet Vercel pour la production. Le plan gratuit Upstash inclut actuellement 250 Mo et 500 000 commandes par mois ; consultez ses quotas en vigueur avant un déploiement public.

Pour Vercel, ajoutez ces variables dans les paramètres du projet et redéployez après avoir renseigné les clés. Les clés ne sont pas incluses dans le dépôt ni dans le code client. Tant que la configuration manque, `/api/chat` renvoie une erreur 503 explicite.

Les appels d'embedding et de génération dépendent du fournisseur configuré et peuvent être facturés par celui-ci. Le service n'envoie pas de requête à Pinecone ou au modèle avant que les variables requises soient présentes.