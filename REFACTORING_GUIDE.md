# Guide de Refactoring - API ClashKing

## 1. Analyse Préliminaire

Avant de commencer le refactoring, analyser le module pour identifier:
- **Code dupliqué** : Blocs de code répétés (validation, stockage, création de réponses)
- **Complexité cognitive élevée** : Fonctions avec trop de niveaux d'indentation ou de logique imbriquée
- **Warnings** : Imports inutilisés, variables non utilisées, paramètres injectés non utilisés
- **Constantes hardcodées** : Chaînes de caractères dupliquées dans le code
- **Type hints incorrects** : Problèmes avec EmailStr, Optional, Union
- **Problèmes de logging** : Utilisation de `print()` au lieu de `logger`
- **Timezone inconsistency** : Utilisation de `pend.now()` sans timezone

## 2. Structure des Fichiers

Pour chaque module, maintenir cette structure:

```
routers/v2/[module]/
├── endpoints.py      # Routes FastAPI
├── utils.py          # Fonctions helper
├── models.py         # Modèles Pydantic
└── __init__.py
```

## 3. Règles de Refactoring - Helper Functions

### 3.1 Quand Créer un Helper

Créer une fonction helper dans `utils.py` si:
- Le code est **dupliqué 3+ fois**
- Le bloc fait **10+ lignes** et a une responsabilité claire
- La logique peut être **testée indépendamment**
- Cela réduit la **complexité cognitive** d'une fonction

### 3.2 Pattern de Nommage des Helpers

```python
# ✅ BON - Verbes d'action descriptifs
async def validate_verification_record(...)
async def store_refresh_token(...)
async def create_auth_response(...)
async def send_password_reset_with_cleanup(...)

# ❌ MAUVAIS - Noms génériques
async def process_data(...)
async def handle_request(...)
async def do_stuff(...)
```

### 3.3 Structure d'un Helper Function

```python
async def helper_name(param1: Type1, param2: Type2, mongo: MongoClient) -> ReturnType:
    """Clear, concise description of what this does.

    Args:
        param1: Description of param1
        param2: Description of param2
        mongo: MongoDB client instance

    Returns:
        Description of return value

    Raises:
        HTTPException: Description of when/why raised
    """
    try:
        # Main logic here
        result = await mongo.collection.operation()
        return result
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={
            "function": "helper_name",
            "param1": safe_log_value(param1)
        })
        raise HTTPException(status_code=500, detail="Clear error message")
```

## 4. Refactoring des Endpoints

### 4.1 Décorateurs - Ordre Important

```python
@router.post("/endpoint-path", response_model=ResponseModel, name="Descriptive Name")
@check_authentication  # Si authentification requise
@linkd.ext.fastapi.inject  # Si injection de dépendances
@capture_endpoint_errors  # Si capture d'erreurs Sentry (optionnel)
async def endpoint_name(...):
```

**IMPORTANT:** Le décorateur `@check_authentication` DOIT être utilisé pour tous les endpoints protégés. Il injecte automatiquement `_user_id` dans les paramètres.

### 4.2 Signature d'un Endpoint Protégé

```python
async def endpoint_name(
    body: RequestModel,  # Si POST/PUT avec body
    request: Request,    # Si besoin des headers/metadata
    _user_id: str = None,  # Injecté par @check_authentication
    _credentials: HTTPAuthorizationCredentials = Depends(security),  # Requis pour auth
    *,
    mongo: MongoClient,  # Injecté par @linkd.ext.fastapi.inject
    _rest: hikari.RESTApp = None  # Si besoin de Discord API
):
```

**Règles importantes:**
- Préfixer avec `_` les paramètres injectés non utilisés directement (`_user_id`, `_credentials`, `_rest`)
- Ne JAMAIS renommer `_user_id` ou le supprimer si `@check_authentication` est présent
- Toujours inclure `_credentials: HTTPAuthorizationCredentials = Depends(security)` pour l'authentification

### 4.3 Pattern d'un Endpoint Refactorisé

```python
async def endpoint_name(...) -> ResponseModel:
    """Clear description of what this endpoint does.

    Args:
        param1: Description
        _user_id: Authenticated user ID (injected by @check_authentication)
        _credentials: HTTP Bearer credentials (required for auth)
        mongo: MongoDB client instance

    Returns:
        ResponseModel: Description of response

    Raises:
        HTTPException: 400 if validation fails
        HTTPException: 404 if resource not found
        HTTPException: 500 if server error
    """
    try:
        # 1. Validation
        validate_input(param1)

        # 2. Business logic using helpers
        result = await helper_function(param1, mongo)

        # 3. Return clean response
        return ResponseModel(**result)

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={
            "endpoint": "/endpoint-path",
            "user_id": _user_id if _user_id else "unknown"
        })
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)
```

## 5. Gestion des Types

### 5.1 EmailStr

`EmailStr` de Pydantic hérite de `str`, donc:

```python
# ✅ BON - Accepter Union pour compatibilité
def hash_email(email: Union[str, EmailStr]) -> str:
    email_normalized = str(email).lower().strip()
    return hashlib.sha256(f"{email_normalized}{secret}".encode()).hexdigest()

# ❌ MAUVAIS - Caster inutilement
email_hash = hash_email(str(req.email))  # Non, req.email suffit

# ✅ BON - Passer directement
email_hash = hash_email(req.email)
```

### 5.2 Type Hints à Ajouter dans utils.py

```python
from typing import Dict, Any, Optional, Union
from pydantic import EmailStr

# Pour toutes les fonctions qui acceptent des emails
def function_name(email: Union[str, EmailStr]) -> str:
    email_str = str(email)  # Convertir pour être sûr
    # ...
```

## 6. Constantes et Literals

### 6.1 Quand Créer une Constante

Si une chaîne de caractères apparaît **3+ fois**, créer une constante:

```python
# Dans endpoints.py ou utils.py (en haut du fichier, après imports)

# Constants
INTERNAL_SERVER_ERROR = "Internal server error"
USER_NOT_FOUND = "User not found"
DEFAULT_AVATAR_URL = "https://clashkingfiles.b-cdn.net/stickers/Troop_HV_Goblin.png"
```

### 6.2 Utilisation des Constantes

```python
# ✅ BON
raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)

# ❌ MAUVAIS
raise HTTPException(status_code=500, detail="Internal server error")
```

## 7. Réduction de Complexité Cognitive

### 7.1 Seuil de Complexité

**Maximum accepté: 15**

Si une fonction dépasse 15, appliquer ces techniques:

### 7.2 Technique 1: Early Returns

```python
# ✅ BON - Early return
async def process_user(user_id: str, mongo: MongoClient):
    user = await mongo.users.find_one({"user_id": user_id})
    if not user:
        return {"message": "User not found"}

    if not user.get("email"):
        return {"message": "Email not set"}

    # Main logic here
    return process_email(user)

# ❌ MAUVAIS - Nested ifs
async def process_user(user_id: str, mongo: MongoClient):
    user = await mongo.users.find_one({"user_id": user_id})
    if user:
        if user.get("email"):
            # Main logic deeply nested
            return process_email(user)
        else:
            return {"message": "Email not set"}
    else:
        return {"message": "User not found"}
```

### 7.3 Technique 2: Extraction de Sous-Fonctions

```python
# ✅ BON - Logique extraite
async def main_function(data, mongo):
    validated = await validate_complex_data(data)
    processed = await process_validated_data(validated, mongo)
    stored = await store_processed_data(processed, mongo)
    return create_response(stored)

# Chaque helper a une complexité < 10

# ❌ MAUVAIS - Tout dans une fonction
async def main_function(data, mongo):
    # 100 lines of nested if/else/try/except
    # Complexité = 25+
```

### 7.4 Technique 3: Cleanup Automatique

Pour les opérations avec cleanup en cas d'erreur:

```python
async def create_and_send_token(user, mongo):
    """Create token and send email, with automatic cleanup on failure.

    Returns:
        Dict with token info

    Raises:
        HTTPException: If send fails (token auto-cleaned)
    """
    # Create token
    token_record = await create_token_record(user, mongo)

    # Send with cleanup on failure
    try:
        await send_email(user.email, token_record["code"])
    except Exception as e:
        # Cleanup token automatically
        await mongo.tokens.delete_one({"_id": token_record["_id"]})
        sentry_sdk.capture_exception(e, tags={"function": "send_token_email"})
        raise HTTPException(status_code=500, detail="Failed to send email")

    return token_record
```

## 8. Optimisations MongoDB

### 8.1 Bulk Operations

Utiliser `bulk_write` pour plusieurs opérations:

```python
# ✅ BON - Bulk write
from pymongo import UpdateOne

operations = [
    UpdateOne(
        {"_id": record["_id"]},
        {"$set": {"processed": True}},
        upsert=False
    )
    for record in records
]

if operations:
    await mongo.collection.bulk_write(operations, ordered=False)

# ❌ MAUVAIS - Loop individuel
for record in records:
    await mongo.collection.update_one(
        {"_id": record["_id"]},
        {"$set": {"processed": True}}
    )
```

### 8.2 Projection Fields

Toujours spécifier les champs nécessaires:

```python
# ✅ BON - Projection explicite
user = await mongo.users.find_one(
    {"user_id": user_id},
    {
        "_id": 0,
        "user_id": 1,
        "username": 1,
        "email_encrypted": 1,
        "avatar_url": 1
    }
)

# ❌ MAUVAIS - Tout charger
user = await mongo.users.find_one({"user_id": user_id})
```

## 9. Logging et Error Handling

### 9.1 Remplacer print() par logger

```python
# ✅ BON
logger.debug(f"Processing user {user_id}")
logger.info(f"User {user_id} created successfully")
logger.warning(f"Invalid attempt for {user_id}")
logger.error(f"Failed to process {user_id}: {error}")

# ❌ MAUVAIS
print(f"Processing user {user_id}")
```

### 9.2 Pattern de Gestion d'Erreur

```python
async def endpoint(...):
    variable_might_fail = None  # Initialize to avoid "referenced before assignment"

    try:
        # Main logic
        variable_might_fail = await operation()

    except HTTPException:
        raise  # Always re-raise HTTPException as-is
    except SpecificException as e:
        # Handle specific cases
        sentry_sdk.capture_exception(e, tags={"type": "specific"})
        raise HTTPException(status_code=400, detail="Specific error")
    except Exception as e:
        # Generic fallback
        sentry_sdk.capture_exception(e, tags={
            "endpoint": "/path",
            "variable": variable_might_fail if variable_might_fail else "unknown"
        })
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR)
```

**Important:** Initialiser les variables qui peuvent être référencées dans les blocs `except`:

```python
# ✅ BON
email = None
user_id = None
try:
    email = extract_email()
    user_id = process_user()
except Exception as e:
    sentry_sdk.capture_exception(e, tags={
        "email": safe_email_log(email) if email else "unknown",
        "user_id": user_id if user_id else "unknown"
    })
```

## 10. Timezone et Timestamps

### 10.1 Utiliser Pendulum avec Timezone

```python
# ✅ BON - Toujours avec timezone
import pendulum as pend

current_time = pend.now(tz=pend.UTC)
expires_at = pend.now(tz=pend.UTC).add(hours=1)
created_at = pend.now(tz=pend.UTC)

# ❌ MAUVAIS - Sans timezone
current_time = pend.now()  # Timezone locale!
```

### 10.2 Validation de Timestamps

```python
async def validate_expires_at(expires_at: Any) -> pend.DateTime:
    """Normalize timestamp to timezone-aware pendulum DateTime."""
    if isinstance(expires_at, str):
        dt = pend.parse(expires_at)
    elif isinstance(expires_at, datetime):
        dt = pend.instance(expires_at)
    elif isinstance(expires_at, pend.DateTime):
        dt = expires_at
    else:
        raise ValueError(f"Invalid expires_at type: {type(expires_at)}")

    # Ensure timezone-aware
    if dt.timezone is None:
        dt = dt.in_timezone(pend.UTC)

    return dt
```

## 11. Documentation

### 11.1 Docstring pour Endpoints

```python
async def endpoint_name(...) -> ResponseModel:
    """Brief one-line description.

    More detailed explanation if needed. Explain business logic,
    authentication requirements, side effects, etc.

    Args:
        param1: Description of param1
        request: FastAPI request object
        _user_id: Authenticated user ID (injected by @check_authentication, not directly used)
        _credentials: HTTP Bearer credentials (required for auth, not directly used)
        mongo: MongoDB client instance

    Returns:
        ResponseModel: Description of what's returned

    Raises:
        HTTPException: 400 if validation fails
        HTTPException: 401 if unauthorized
        HTTPException: 404 if resource not found
        HTTPException: 500 if server error occurs
    """
```

### 11.2 Docstring pour Helpers

```python
async def helper_function(param: Type, mongo: MongoClient) -> Dict[str, Any]:
    """Brief one-line description of what this helper does.

    Args:
        param: Description
        mongo: MongoDB client instance

    Returns:
        Dict containing:
            - key1: description
            - key2: description

    Raises:
        HTTPException: When and why it's raised
    """
```

## 12. Checklist de Refactoring

Utiliser cette checklist pour chaque module:

### Phase 1: Analyse
- [ ] Lire tous les endpoints du module
- [ ] Identifier le code dupliqué (3+ occurrences)
- [ ] Noter les fonctions avec complexité > 15
- [ ] Lister tous les warnings (imports, variables, types)
- [ ] Identifier les chaînes hardcodées dupliquées

### Phase 2: utils.py
- [ ] Créer les constantes pour literals dupliqués
- [ ] Extraire les helpers pour code dupliqué
- [ ] Ajouter les imports nécessaires (Union, EmailStr, etc.)
- [ ] Ajouter docstrings complets à tous les helpers
- [ ] Mettre à jour les type hints pour accepter EmailStr

### Phase 3: endpoints.py
- [ ] Ajouter les imports des nouveaux helpers
- [ ] Ajouter les imports des constantes (ou les définir)
- [ ] Vérifier que `@check_authentication` est présent sur endpoints protégés
- [ ] Vérifier les signatures avec `_user_id` et `_credentials`
- [ ] Remplacer code dupliqué par appels aux helpers
- [ ] Remplacer literals par constantes
- [ ] Remplacer `print()` par `logger.debug/info/warning/error`
- [ ] Remplacer `pend.now()` par `pend.now(tz=pend.UTC)`
- [ ] Préfixer paramètres inutilisés avec `_`
- [ ] Initialiser variables qui peuvent être référencées dans except
- [ ] Ajouter/compléter docstrings pour tous les endpoints

### Phase 4: Réduction Complexité
- [ ] Identifier fonctions avec complexité > 15
- [ ] Appliquer early returns où possible
- [ ] Extraire sous-fonctions pour logique complexe
- [ ] Créer helpers avec cleanup automatique
- [ ] Vérifier nouvelle complexité < 15

### Phase 5: Validation
- [ ] Compiler avec `python3 -m py_compile endpoints.py utils.py`
- [ ] Vérifier qu'il n'y a plus de warnings
- [ ] Vérifier que tous les tests passent (si présents)
- [ ] Relire le code pour cohérence

## 13. Exemples de Refactoring

### Exemple 1: Création de Token avec Cleanup

**AVANT (Complexité: 19)**
```python
async def forgot_password(req: ForgotPasswordRequest, *, mongo: MongoClient):
    try:
        email_hash = hash_email(req.email)
        user = await mongo.users.find_one({"email_hash": email_hash})

        if not user:
            return {"message": "If account exists..."}

        # Check existing tokens
        existing = await mongo.reset_tokens.find_one({
            "email_hash": email_hash,
            "used": False,
            "expires_at": {"$gt": pend.now()}
        })

        if existing:
            await mongo.reset_tokens.delete_one({"_id": existing["_id"]})

        # Create token
        reset_code = generate_code()
        expires_at = pend.now().add(hours=1)

        try:
            reset_record = {
                "user_id": user["user_id"],
                "email_hash": email_hash,
                "reset_code": reset_code,
                "expires_at": expires_at,
                "used": False
            }
            result = await mongo.reset_tokens.insert_one(reset_record)
            reset_record["_id"] = result.inserted_id
        except Exception as e:
            sentry_sdk.capture_exception(e)
            raise HTTPException(500, "Failed to create token")

        # Decrypt email
        try:
            email = await decrypt_data(user["email_encrypted"])
        except Exception as e:
            await mongo.reset_tokens.delete_one({"_id": reset_record["_id"]})
            raise HTTPException(500, "Failed to decrypt")

        # Send email
        try:
            await send_reset_email(email, reset_code)
        except Exception as e:
            await mongo.reset_tokens.delete_one({"_id": reset_record["_id"]})
            raise HTTPException(500, "Failed to send email")

        return {"message": "If account exists..."}
    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise HTTPException(500, "Internal server error")
```

**APRÈS (Complexité: 8)**
```python
# Dans utils.py:
async def create_password_reset_token(user, email_hash, mongo):
    """Create password reset token with cleanup of old tokens."""
    # Cleanup old tokens
    await mongo.reset_tokens.delete_many({
        "email_hash": email_hash,
        "used": False,
        "expires_at": {"$gt": pend.now(tz=pend.UTC)}
    })

    # Create new token
    reset_code = generate_verification_code()
    expires_at = pend.now(tz=pend.UTC).add(hours=1)

    try:
        reset_record = {
            "user_id": user["user_id"],
            "email_hash": email_hash,
            "reset_code": reset_code,
            "expires_at": expires_at,
            "created_at": pend.now(tz=pend.UTC),
            "used": False
        }
        result = await mongo.reset_tokens.insert_one(reset_record)
        reset_record["_id"] = result.inserted_id
        return reset_record
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"function": "create_reset_token"})
        raise HTTPException(500, "Failed to create reset token")

async def send_password_reset_with_cleanup(user, reset_record, reset_code, mongo):
    """Decrypt email and send reset, with cleanup on failure."""
    try:
        email = await decrypt_data(user["email_encrypted"])
        if not email:
            raise ValueError("Email is empty")
    except Exception as e:
        await mongo.reset_tokens.delete_one({"_id": reset_record["_id"]})
        sentry_sdk.capture_exception(e, tags={"function": "decrypt_for_reset"})
        raise HTTPException(500, "Failed to process reset")

    try:
        username = user.get("username", "User")
        await send_password_reset_email_with_code(email, username, reset_code)
    except Exception as e:
        await mongo.reset_tokens.delete_one({"_id": reset_record["_id"]})
        sentry_sdk.capture_exception(e, tags={"function": "send_reset_email"})
        raise HTTPException(500, "Failed to send reset email")

# Dans endpoints.py:
async def forgot_password(req: ForgotPasswordRequest, *, mongo: MongoClient):
    """Request a password reset code via email."""
    try:
        PasswordValidator.validate_email(req.email)

        email_hash = hash_email(req.email)
        user = await mongo.users.find_one({"email_hash": email_hash})

        if not user or "email" not in user.get("auth_methods", []):
            return {"message": "If an account with this email exists..."}

        reset_record = await create_password_reset_token(user, email_hash, mongo)
        await send_password_reset_with_cleanup(user, reset_record, reset_record["reset_code"], mongo)

        return {"message": "If an account with this email exists..."}

    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={"endpoint": "/auth/forgot-password"})
        raise HTTPException(500, INTERNAL_SERVER_ERROR)
```

### Exemple 2: Endpoint avec @check_authentication

**Structure correcte:**

```python
@router.get("/me", response_model=UserInfo, name="Get current user info")
@check_authentication
@linkd.ext.fastapi.inject
async def get_current_user_info(
    _user_id: str = None,  # Injecté par @check_authentication
    _credentials: HTTPAuthorizationCredentials = Depends(security),
    *,
    mongo: MongoClient,
    _rest: hikari.RESTApp = None
) -> UserInfo:
    """Get current authenticated user's information.

    Args:
        _user_id: Authenticated user ID (injected by @check_authentication)
        _credentials: HTTP Bearer credentials (required for auth)
        mongo: MongoDB client instance
        _rest: Discord REST API client (injected, not used)

    Returns:
        UserInfo: Current user's information

    Raises:
        HTTPException: 404 if user not found
        HTTPException: 500 if server error
    """
    try:
        # Utiliser _user_id injecté par le décorateur
        user = await mongo.users.find_one({"user_id": _user_id})

        if not user:
            raise HTTPException(404, USER_NOT_FOUND)

        return UserInfo(
            user_id=user["user_id"],
            username=user.get("username", "Unknown"),
            avatar_url=user.get("avatar_url", DEFAULT_AVATAR_URL)
        )

    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e, tags={
            "endpoint": "/auth/me",
            "user_id": _user_id
        })
        raise HTTPException(500, INTERNAL_SERVER_ERROR)
```

---

## Points Clés à Retenir

1. **@check_authentication** doit toujours être utilisé pour les endpoints protégés
2. Les paramètres injectés inutilisés doivent être préfixés avec `_`
3. `EmailStr` hérite de `str` - pas besoin de cast, juste `Union[str, EmailStr]` dans les type hints
4. Toujours utiliser `pend.now(tz=pend.UTC)` pour la cohérence des timezones
5. Initialiser les variables qui peuvent être référencées dans les blocs `except`
6. Créer des constantes pour les literals dupliqués (3+ fois)
7. Extraire des helpers quand la complexité > 15 ou code dupliqué 3+ fois
8. Toujours re-raise `HTTPException` tel quel dans les blocs except
9. Utiliser `logger` au lieu de `print()`
10. Ajouter des docstrings complets partout
