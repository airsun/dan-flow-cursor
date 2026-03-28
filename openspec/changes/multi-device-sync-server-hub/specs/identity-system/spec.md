## ADDED Requirements

### Requirement: First-access setup flow
The system SHALL detect when no identities exist and guide the first user through identity creation, automatically granting admin status.

#### Scenario: Empty system first access
- **WHEN** a browser accesses the Hub and the server has zero identities
- **THEN** the server SHALL serve a setup page where the user enters an identity name, and upon submission the server SHALL create the identity with `is_admin: true`, generate a token, generate call sign suggestions, and display the token exactly once with a reminder to save it

#### Scenario: System already initialized
- **WHEN** a browser accesses the Hub and at least one identity exists
- **THEN** the server SHALL NOT show the setup flow and SHALL require a valid token to proceed

### Requirement: Token generation
The system SHALL generate cryptographically secure tokens with a recognizable prefix.

#### Scenario: Token format
- **WHEN** a new identity is created
- **THEN** the server SHALL generate a token in the format `df_` followed by 40 cryptographically random alphanumeric characters

#### Scenario: Token storage
- **WHEN** a token is generated
- **THEN** the server SHALL store only the SHA-256 hash of the token in the database and return the plaintext token exactly once in the creation response

### Requirement: Token authentication
All API endpoints (except the first-access setup) SHALL require a valid, enabled identity token.

#### Scenario: Valid token in Authorization header
- **WHEN** a request includes `Authorization: Bearer df_xxx` and the token hash matches an enabled identity
- **THEN** the request SHALL be authenticated and the identity attached to the request context

#### Scenario: Valid token in localStorage flow
- **WHEN** a browser has a token in localStorage
- **THEN** the frontend SHALL include it as a Bearer token in all API requests

#### Scenario: No token provided
- **WHEN** a request to a protected endpoint lacks a token
- **THEN** the server SHALL respond with HTTP 401 and the frontend SHALL show a token input prompt

#### Scenario: Disabled identity token
- **WHEN** a request includes a token belonging to a disabled identity
- **THEN** the server SHALL respond with HTTP 403 and a message indicating the identity has been disabled

### Requirement: Identity name uniqueness
Identity names SHALL be unique across the system.

#### Scenario: Duplicate name attempt
- **WHEN** a user attempts to create an identity with a name that already exists
- **THEN** the server SHALL reject the creation with HTTP 409 and suggest alternatives by appending `-2`, `-3`, etc. to the requested name

#### Scenario: Case sensitivity
- **WHEN** comparing identity names for uniqueness
- **THEN** the comparison SHALL be case-insensitive (e.g., "GuNegg" and "gunegg" are the same)

### Requirement: Call sign generation
The system SHALL generate a call sign (emoji + short English phrase) for each identity that has a perceptible association with the identity name.

#### Scenario: Call sign creation
- **WHEN** a new identity is being created
- **THEN** the server SHALL call the Claude API to generate 3 call sign suggestions that are associatively linked to the identity name (by sound, meaning, wordplay, or visual association)

#### Scenario: Call sign selection
- **WHEN** call sign suggestions are presented to the user
- **THEN** the user SHALL be able to select one of the 3 suggestions, request a new batch, or enter a custom call sign

#### Scenario: Call sign format
- **WHEN** a call sign is generated or entered
- **THEN** it SHALL consist of exactly one emoji followed by 1-3 English words, total length not exceeding 30 characters

#### Scenario: Call sign display
- **WHEN** an identity is displayed anywhere in the Hub (session cards, filters, admin panel)
- **THEN** the call sign SHALL be shown alongside or instead of the raw identity name

### Requirement: Admin identity management
The admin identity SHALL be able to create, enable, and disable other identities.

#### Scenario: Create new identity
- **WHEN** an admin requests identity creation via `POST /api/identities` with a name
- **THEN** the server SHALL create the identity, generate a token (returned once), generate call sign suggestions, and set `enabled: true`

#### Scenario: Disable identity
- **WHEN** an admin requests `POST /api/identities/{id}/disable`
- **THEN** the server SHALL set `enabled: false` on that identity, immediately invalidating all requests using that identity's token

#### Scenario: Enable identity
- **WHEN** an admin requests `POST /api/identities/{id}/enable`
- **THEN** the server SHALL set `enabled: true`, restoring access for that identity's token

#### Scenario: Admin cannot disable self
- **WHEN** an admin attempts to disable their own identity
- **THEN** the server SHALL reject with HTTP 400 to prevent lockout

#### Scenario: List identities
- **WHEN** an admin requests `GET /api/identities`
- **THEN** the server SHALL return all identities with: name, call sign, is_admin, enabled, created_at, last sync time, and files tracked count

### Requirement: Non-admin identity permissions
Non-admin identities SHALL have read access to all sessions and write access only to their own sync data.

#### Scenario: Non-admin views sessions
- **WHEN** a non-admin identity requests session data
- **THEN** the server SHALL return sessions from all identities (full visibility)

#### Scenario: Non-admin sync push
- **WHEN** a non-admin identity pushes sync data
- **THEN** the server SHALL accept it and associate it with that identity

#### Scenario: Non-admin attempts admin action
- **WHEN** a non-admin identity attempts to create/disable/enable identities
- **THEN** the server SHALL respond with HTTP 403
