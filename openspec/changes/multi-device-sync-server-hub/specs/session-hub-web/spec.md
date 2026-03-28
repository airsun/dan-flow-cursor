## ADDED Requirements

### Requirement: Multi-device unified session view
The Hub SHALL display all sessions from all identities in a single unified view, grouped by project.

#### Scenario: Sessions from multiple devices in same project
- **WHEN** two identities have synced sessions belonging to the same project
- **THEN** the Hub SHALL display them under a single project group, each session tagged with its identity's call sign

#### Scenario: Project card summary
- **WHEN** a project has sessions from multiple identities
- **THEN** the project card SHALL show: project name, total session count, per-identity session counts with call signs, overall last activity time, and aggregate state (active if any session is active)

### Requirement: Identity filtering
The Hub SHALL allow filtering the session view by identity.

#### Scenario: Filter by single identity
- **WHEN** the user selects an identity from the filter dropdown
- **THEN** the Hub SHALL show only sessions belonging to that identity

#### Scenario: Show all identities
- **WHEN** the identity filter is set to "All"
- **THEN** the Hub SHALL show sessions from all enabled identities

#### Scenario: Identity indicator on session cards
- **WHEN** displaying a session card in the "All" view
- **THEN** the card SHALL show the identity's call sign emoji as a badge

### Requirement: Session status display
The Hub SHALL display real-time session status with visual indicators consistent with the current local hub design.

#### Scenario: Executing session
- **WHEN** a session's computed state is `executing`
- **THEN** the Hub SHALL show a green pulsing dot with breathing animation

#### Scenario: Waiting input session (hard)
- **WHEN** a session's state is `waiting_input` with `input_type: hard`
- **THEN** the Hub SHALL show an amber pulsing dot, a "BLOCKED" badge, and the question text as a snippet, and the card SHALL be sorted to the top

#### Scenario: Waiting input session (soft)
- **WHEN** a session's state is `waiting_input` with `input_type: soft`
- **THEN** the Hub SHALL show an amber dot with an "IDLE?" badge

#### Scenario: Idle session
- **WHEN** a session's state is `idle`
- **THEN** the Hub SHALL show a gray dot

### Requirement: Sub-agent display
The Hub SHALL display sub-agent sessions as part of their parent session, not as standalone cards.

#### Scenario: Parent with sub-agents
- **WHEN** a parent session has associated sub-agent sessions
- **THEN** the Hub SHALL show a dot matrix on the parent card representing sub-agent states, and a sub-agent count badge

#### Scenario: Sub-agent detail overlay
- **WHEN** the user clicks the sub-agent dot matrix on a parent card
- **THEN** the Hub SHALL show an overlay panel listing all sub-agents with their status, last message snippet, and a link to view the sub-agent's full conversation

### Requirement: Session conversation view
The Hub SHALL display the full conversation of a selected session with proper formatting.

#### Scenario: View session messages
- **WHEN** the user clicks a session card
- **THEN** the Hub SHALL load and display all messages for that session with Markdown rendering, code syntax highlighting, and role-based visual styling (user/assistant/thinking/progress)

#### Scenario: Thinking content collapsible
- **WHEN** a message is classified as thinking content
- **THEN** the Hub SHALL render it in a collapsible block with muted styling

### Requirement: Collapsible sidebar
The Hub SHALL have a collapsible sidebar showing the flat session list.

#### Scenario: Expanded sidebar
- **WHEN** the sidebar is expanded
- **THEN** it SHALL show session items with status dot, project name, identity call sign emoji, session snippet, and sub-agent count badge

#### Scenario: Collapsed sidebar
- **WHEN** the sidebar is collapsed
- **THEN** it SHALL show only status dots and identity emoji badges for each session

### Requirement: Auto-refresh
The Hub SHALL automatically refresh session data at regular intervals.

#### Scenario: Periodic refresh
- **WHEN** the Hub is open in a browser
- **THEN** it SHALL poll the sessions API every 2 seconds and update the UI without full page reload

#### Scenario: New session appears
- **WHEN** a new session is synced to the server between polls
- **THEN** it SHALL appear in the Hub on the next poll cycle

### Requirement: Admin panel
The Hub SHALL include an admin panel accessible to admin identities for managing identities and viewing sync health.

#### Scenario: Access admin panel
- **WHEN** an admin identity clicks the admin/settings icon in the Hub
- **THEN** the Hub SHALL show the identity management panel with all identities, their call signs, status, and sync health

#### Scenario: Create identity from admin panel
- **WHEN** an admin clicks "New Identity" and enters a name
- **THEN** the Hub SHALL call the identity creation API, display call sign suggestions for selection, and show the generated token exactly once

#### Scenario: Toggle identity status
- **WHEN** an admin clicks enable/disable on an identity
- **THEN** the Hub SHALL call the corresponding API and update the UI immediately

### Requirement: Token entry flow
The Hub SHALL provide a minimal flow for entering a token when no valid token is in localStorage.

#### Scenario: No token in localStorage
- **WHEN** the browser accesses the Hub without a stored token
- **THEN** the Hub SHALL show a simple token input field with a paste button, no other UI elements

#### Scenario: Invalid token entered
- **WHEN** the user enters a token that the server rejects
- **THEN** the Hub SHALL show an error message and keep the input field visible

#### Scenario: Valid token entered
- **WHEN** the user enters a valid token
- **THEN** the Hub SHALL store it in localStorage and immediately load the full Hub interface
