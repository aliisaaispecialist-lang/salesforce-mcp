# Salesforce REST API Cartography — Tool Catalogue for salesforce-mcp

**API version documented**: v67.0 (Summer '26) — current as of research date 2026-08-06. Master resource list: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_list.htm

**Versioning strategy recommendation**: pin the MCP server to a single, config-driven API version (e.g. `v61.0` LTS-ish, or track "current minus 1" to avoid beta-instability), discovered/validated at startup via `list_api_versions`, NOT hardcoded per call. Salesforce guarantees backward compatibility per version forever, so pinning is safe; only bump deliberately when new fields/resources are needed. Never auto-follow "latest" silently — a MyDomain org may lag the newest release train.

---

## 1. MASTER TOOL TABLE

Legend — Safety: `RO`=read-only, `ADD`=additive/create, `DESTR`=destructive (overwrite/delete), `IRREV`=irreversible (hard delete/purge, no undo). Idempotent = repeating the call with same input has same effect.

| # | Tool name | Method | Path template | Safety | Idempotent | One-line description |
|---|---|---|---|---|---|---|
| 1 | `list_api_versions` | GET | `/services/data` | RO | Y | List all Salesforce REST API versions available on this org's host. |
| 2 | `list_resources_for_version` | GET | `/services/data/vXX.X` | RO | Y | List every top-level resource URI available under a specific API version. |
| 3 | `list_objects` | GET | `/sobjects` | RO | Y | List all sObjects (standard + custom) visible to the user, with basic flags (queryable, createable, etc). |
| 4 | `describe_object` | GET | `/sobjects/{obj}/describe` | RO | Y | Full metadata for one object: every field, type, picklist values, relationships, record types. Large response — truncate. |
| 5 | `get_object_basic_info` | GET | `/sobjects/{obj}` | RO | Y | Lightweight object metadata + recently-used record IDs + related resource URLs (cheaper than full describe). |
| 6 | `check_limits` | GET | `/limits` | RO | Y | Org-wide limit allocations and remaining consumption (API calls, storage, async jobs, etc). |
| 7 | `get_record_count` | GET | `/limits/recordCount` | RO | Y | Approximate record counts per sObject (for capacity/storage checks). |
| 8 | `get_record` | GET | `/sobjects/{obj}/{id}` | RO | Y | Retrieve one record by Salesforce ID, optionally a field subset. |
| 9 | `create_record` | POST | `/sobjects/{obj}` | ADD | N | Create one new record of the given object type. |
| 10 | `update_record` | PATCH | `/sobjects/{obj}/{id}` | DESTR | Y | Partially update fields on an existing record by ID (no response body). |
| 11 | `delete_record` | DELETE | `/sobjects/{obj}/{id}` | IRREV | Y | Delete one record by ID (goes to Recycle Bin, but tool should still confirm). |
| 12 | `get_record_by_external_id` | GET | `/sobjects/{obj}/{field}/{value}` | RO | Y | Retrieve a record using an external-ID field instead of Salesforce record ID. |
| 13 | `upsert_record_by_external_id` | PATCH | `/sobjects/{obj}/{field}/{value}` | DESTR | N* | Create-or-update a record keyed by external ID. Not strictly idempotent across concurrent calls (300 on ambiguous match). |
| 14 | `create_record_with_external_id_seed` | POST | `/sobjects/{obj}/{field}/{value}` | ADD | N | Create a record while pre-seeding an external ID field (v37.0+; Id itself usable as the field). |
| 15 | `delete_record_by_external_id` | DELETE | `/sobjects/{obj}/{field}/{value}` | IRREV | Y | Delete a record located via external-ID field/value. |
| 16 | `get_blob_field` | GET | `/sobjects/{obj}/{id}/{blobField}` | RO | Y | Download binary content of a blob field (Attachment.Body, ContentVersion.VersionData, Document.Body, etc). |
| 17 | `get_rich_text_image` | GET | `/sobjects/{obj}/{id}/richTextImageFields/{field}/{contentReferenceId}` | RO | Y | Retrieve an inline image embedded in a rich-text area field. |
| 18 | `get_deleted_records` | GET | `/sobjects/{obj}/deleted?start=&end=` | RO | Y | List records of a type soft-deleted (in Recycle Bin) within a time window — for replication/sync. |
| 19 | `get_updated_records` | GET | `/sobjects/{obj}/updated?start=&end=` | RO | Y | List record IDs of a type updated within a time window — for replication/sync (no field data). |
| 20 | `soql_query` | GET | `/query?q={soql}` | RO | Y | Execute a SOQL query and return the first page of results (≤2000 rows). |
| 21 | `soql_query_long` | POST | `/query` (body: `q`) | RO | Y | Execute a SOQL query too long for a GET URL (>~2000 chars encoded) via POST body. |
| 22 | `soql_query_more` | GET | `nextRecordsUrl` (opaque, from prior response) | RO | Y | Fetch the next page of a previously-started SOQL query. |
| 23 | `soql_query_all` | GET | `/queryAll?q={soql}` | RO | Y | Execute a SOQL query including soft-deleted and archived records. |
| 24 | `soql_query_all_more` | GET | `nextRecordsUrl` (from queryAll) | RO | Y | Fetch next page of a queryAll result set. |
| 25 | `explain_query_plan` | GET | `/query?explain={soql}` | RO | Y | Return the query optimizer's plan/cost estimate instead of executing the query (Beta). |
| 26 | `sosl_search` | GET | `/search?q={sosl}` | RO | Y | Execute a full SOSL free-text search across multiple objects. |
| 27 | `parameterized_search` | GET | `/parameterizedSearch?q=` | RO | Y | Simple keyword search without SOSL syntax, params in the URL. |
| 28 | `parameterized_search_advanced` | POST | `/parameterizedSearch` (JSON body) | RO | Y | Same as above but with a structured JSON body for complex filters/field lists too large for a query string. |
| 29 | `get_search_scope_order` | GET | `/search/scopeOrder` | RO | Y | Objects ordered by the user's search-frequency (drives default search-object ordering in UI). |
| 30 | `get_search_suggested_queries` | GET | `/search/suggestSearchQueries?q=&language=` | RO | Y | Autocomplete-style query suggestions from past searches. |
| 31 | `get_search_suggested_article_titles` | GET | `/search/suggestTitleMatches?q=&language=&publishStatus=` | RO | Y | Suggest matching Knowledge article titles. |
| 32 | `get_search_result_layouts` | GET | `/searchlayout?q={objects}` | RO | Y | Column/layout definitions used to render search results for given objects. |
| 33 | `list_list_views` | GET | `/sobjects/{obj}/listviews` | RO | Y | List all list views defined for an object. |
| 34 | `get_list_view` | GET | `/sobjects/{obj}/listviews/{id}` | RO | Y | Metadata for one specific list view. |
| 35 | `get_list_view_results` | GET | `/sobjects/{obj}/listviews/{id}/results` | RO | Y | Execute a list view's underlying query and return row data. |
| 36 | `describe_list_view` | GET | `/sobjects/{obj}/listviews/{id}/describe` | RO | Y | Column metadata + SOQL behind a list view. |
| 37 | `get_recent_list_views` | GET | `/sobjects/{obj}/listviews/recent` | RO | Y | Recently accessed list views for an object. |
| 38 | `describe_object_layouts` | GET | `/sobjects/{obj}/describe/layouts` | RO | Y | Page layout assignments/definitions for an object. |
| 39 | `describe_global_layouts` | GET | `/sobjects/Global/describe/layouts` | RO | Y | Layout info shared across multiple objects (Global describe-layouts variant). |
| 40 | `describe_named_layout` | GET | `/sobjects/{obj}/describe/namedLayouts/{layoutName}` | RO | Y | One alternate/named layout (e.g. console views). |
| 41 | `describe_compact_layouts` | GET | `/sobjects/{obj}/describe/compactLayouts` | RO | Y | Compact layout definitions for one object (mobile/highlights panel). |
| 42 | `describe_approval_layouts` | GET | `/sobjects/{obj}/describe/approvalLayouts` | RO | Y | Approval-process page layouts for an object. |
| 43 | `list_compact_layouts_multi` | GET | `/compactLayouts?q={objectList}` | RO | Y | Compact layouts for several objects in one call. |
| 44 | `composite_request` | POST | `/composite` | varies | N | Chain up to 25 dependent sub-requests (can reference earlier results) in one round trip. |
| 45 | `composite_batch` | POST | `/composite/batch` | varies | N | Run up to 25 independent sub-requests in one round trip (no inter-request referencing). |
| 46 | `composite_graph` | POST | `/composite/graph` | varies | N | Run multiple named "graphs" of composite requests, each with its own transactional boundary, in one call. |
| 47 | `create_records_with_children` | POST | `/composite/tree/{obj}` | ADD | N | Create a parent record plus nested child records (up to 200 total, 5 levels deep) atomically. |
| 48 | `collections_create_records` | POST | `/composite/sobjects` | ADD | N | Create up to 200 records (mixed types allowed) in one call, with optional all-or-none rollback. |
| 49 | `collections_update_records` | PATCH | `/composite/sobjects` | DESTR | Y | Update up to 200 existing records in one call. |
| 50 | `collections_upsert_records` | PATCH | `/composite/sobjects/{obj}/{externalIdField}` | DESTR | N | Upsert up to 200 records of one type keyed by external ID. |
| 51 | `collections_get_records` | GET | `/composite/sobjects/{obj}?ids=&fields=` | RO | Y | Fetch multiple same-type records by ID list plus explicit field list (no blobs). |
| 52 | `collections_delete_records` | DELETE | `/composite/sobjects?ids=` | IRREV | Y | Delete up to 200 records (mixed types) by ID in one call. |
| 53 | `list_invocable_actions_standard` | GET | `/actions/standard` | RO | Y | List built-in invocable actions (e.g. `emailSimple`, `chatterPost`, `submit`). |
| 54 | `list_invocable_actions_custom` | GET | `/actions/custom` | RO | Y | List custom invocable action types available in the org (e.g. Flow-based). |
| 55 | `describe_invocable_action` | GET | `/actions/{standard\|custom}/{type}/{name}` | RO | Y | Input/output parameter schema for one invocable action. |
| 56 | `invoke_standard_action` | POST | `/actions/standard/{actionName}` | ADD/DESTR | N | Execute a standard invocable action (e.g. send email, post to Chatter). |
| 57 | `invoke_custom_action` | POST | `/actions/custom/{type}/{name}` | ADD/DESTR | N | Execute a custom invocable action (e.g. an autolaunched Flow). |
| 58 | `list_quick_actions_global` | GET | `/quickActions` | RO | Y | List global quick actions (not tied to a specific object). |
| 59 | `get_quick_action_details` | GET | `/quickActions/{actionName}` | RO | Y | Field layout/config for one global quick action. |
| 60 | `get_quick_action_default_values` | GET | `/quickActions/{actionName}/defaultValues` | RO | Y | Pre-populated default field values for a quick action form. |
| 61 | `invoke_quick_action` | POST | `/quickActions/{actionName}` | ADD | N | Execute a global quick action (e.g. create a record via a UI-defined action). |
| 62 | `list_sobject_quick_actions` | GET | `/sobjects/{obj}/quickActions` | RO | Y | List quick actions scoped to one object. |
| 63 | `get_sobject_quick_action_details` | GET | `/sobjects/{obj}/quickActions/{actionName}` | RO | Y | Field layout/config of an object-scoped quick action. |
| 64 | `invoke_sobject_quick_action` | POST | `/sobjects/{obj}/quickActions/{actionName}` | ADD | N | Execute an object-scoped quick action (e.g. "Log a Call" on a record). |
| 65 | `list_platform_actions` | GET | `/sobjects/PlatformAction` | RO | Y | Query actions surfaced in the Salesforce UI action bar for a context. |
| 66 | `get_related_records` | GET | `/sobjects/{obj}/{id}/{relationshipName}` | RO | Y | Traverse a lookup/master-detail relationship from a record via friendly URL. |
| 67 | `update_related_record` | PATCH | `/sobjects/{obj}/{id}/{relationshipName}` | DESTR | Y | Update the single related record reached via a relationship traversal. |
| 68 | `delete_related_record` | DELETE | `/sobjects/{obj}/{id}/{relationshipName}` | IRREV | Y | Delete the related record reached via a relationship traversal. |
| 69 | `get_relevant_items` | GET | `/sobjects/relevantItems` | RO | Y | The current user's most-relevant records/objects (MRU-derived). |
| 70 | `get_recently_viewed` | GET | `/recent` | RO | Y | Records the current user most recently viewed/referenced, across objects. |
| 71 | `list_approval_processes` | GET | `/process/approvals` | RO | Y | List approval processes available in the org (optionally scoped to an object). |
| 72 | `submit_for_approval` | POST | `/process/approvals` | ADD | N | Submit one or more records into an approval process, or approve/reject/reassign a pending step. |
| 73 | `list_workflow_rules` | GET | `/process/rules` | RO | Y | List all active workflow rules org-wide. |
| 74 | `list_workflow_rules_for_object` | GET | `/process/rules/{obj}` | RO | Y | List active workflow rules for one object. |
| 75 | `trigger_workflow_rules` | POST | `/process/rules/{obj}` | DESTR | N | Force-evaluate workflow rules against specified record IDs. |
| 76 | `get_user_password_status` | GET | `/sobjects/User/{id}/password` | RO | Y | Password expiration/history metadata for a user (no plaintext password ever returned). |
| 77 | `set_user_password` | POST | `/sobjects/User/{id}/password` | DESTR | Y | Set a specific new password for a user. |
| 78 | `reset_user_password` | DELETE | `/sobjects/User/{id}/password` | IRREV | Y | Reset a user's password to a new system-generated one (invalidates the old one). |
| 79 | `list_app_menu` | GET | `/appMenu/AppSwitcher` | RO | Y | List apps in the Lightning app switcher. |
| 80 | `list_mobile_app_menu` | GET | `/appMenu/Salesforce1` | RO | Y | List apps in the Salesforce mobile nav menu. |
| 81 | `list_tabs` | GET | `/tabs` | RO | Y | List all tabs (Lightning pages included) visible to the user. |
| 82 | `get_theme` | GET | `/theme` | RO | Y | Icons/colors used per-object for current theme (branding lookups). |
| 83 | `get_knowledge_article` | GET | `/support/knowledgeArticles/{id}` | RO | Y | Fetch a published Knowledge article's full fields. |
| 84 | `list_data_category_groups` | GET | `/support/dataCategoryGroups` | RO | Y | List Knowledge/Case data category groups visible to the user. |
| 85 | `get_data_category_detail` | GET | `/support/dataCategoryGroups/{group}/dataCategories/{category}` | RO | Y | Category hierarchy/properties for one data category. |
| 86 | `get_platform_event_schema_by_name` | GET | `/sobjects/{eventName}/eventSchema` | RO | Y | Avro/JSON schema for a Platform Event by its API name. |
| 87 | `get_platform_event_schema_by_id` | GET | `/event/eventSchema/{schemaId}` | RO | Y | Same schema lookup, keyed by opaque schema ID instead of name. |
| 88 | `generate_openapi_spec` | POST | `/async/specifications/oas3` | RO (read of metadata) | N | Kick off async generation of an OpenAPI 3.0 document for chosen sObjects/resources (Beta). |
| 89 | `get_openapi_spec_status` | GET | `/async/specifications/oas3/{locatorId}` | RO | Y | Poll status of a previously requested OpenAPI generation job. |
| 90 | `get_openapi_spec_result` | GET | `/async/specifications/oas3/{locatorId}/results` | RO | Y | Retrieve the finished OpenAPI 3.0 JSON document (available 48h). |

**Deliberately out of v1 scope** (see §5): Bulk API 2.0 Jobs (`/jobs`), Async Queries (`/async-queries`), Metadata API, Tooling API, UI API, Analytics/Wave, Connect REST API (Chatter/files/communities), Scheduler resources, Consent/Portability, Lightning usage-metrics objects, Streaming Channel push, industry-cloud connect resources (FSC/Health/Manufacturing/CG). These are separate API families or clearly niche; see full reasoning in §5.

---

## 2. DETAILED TOOL GROUPS

### 2.1 Discovery / Meta

**`list_api_versions`** — `GET /services/data`
- No auth strictly required (Salesforce serves this unauthenticated), no parameters.
- Response: JSON array of `{version, label, url}`. Use to validate the server's configured version is still supported before startup.
- Source: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_versions.htm

**`list_resources_for_version`** — `GET /services/data/vXX.X`
- Path param: `version` (e.g. `v61.0`), required.
- Response: map of resource-name → relative URL (sobjects, query, search, limits, composite, tooling, etc). Useful as a live capability probe — some resources are edition-gated.
- Source: resources_list.htm (root reference)

**`list_objects`** (Describe Global) — `GET /sobjects`
- No params beyond auth. Response: `encoding`, `maxBatchSize`, `sobjects[]` array each with `name`, `label`, `keyPrefix`, `queryable`, `createable`, `updateable`, `deletable`, `custom`, `urls`.
- Truncation: for orgs with 1000+ objects (packages installed), return name/label/flags only by default; require an explicit "include full" flag to inline `urls`.
- Source: resources_list.htm; https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_sobject_basic_info.htm (basic-info sibling)

**`describe_object`** — `GET /sobjects/{obj}/describe` — **critical tool**
- Path param: `obj` (API name, required).
- Response is large: `fields[]` (each with `name`, `type`, `label`, `length`, `precision`, `scale`, `picklistValues[]`, `referenceTo[]`, `relationshipName`, `nillable`, `createable`, `updateable`, `unique`, `defaultValue`, `calculated`), `childRelationships[]`, `recordTypeInfos[]`, `supportedScopes[]`, plus flags (`layoutable`, `mergeable`, `queryable`, `searchable`, `triggerable`).
- **Truncation strategy**: this is the single most token-expensive tool. Default to returning only `name/type/label/required/createable/updateable/referenceTo/picklistValues(labels only)` per field, dropping verbose per-field permission flags and childRelationships unless a `verbose=true` param is passed. Cache aggressively (object schemas change rarely) — this is a strong candidate for ETag/If-Modified-Since caching (see §2.9).
- Source: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_sobject_describe.htm

**`get_object_basic_info`** — `GET /sobjects/{obj}`
- Cheaper alternative to full describe: object-level flags + `recentItems[]` + `urls` map to child resources (describe, layouts, rowTemplate, etc). Good default "what is this object" tool before paying the describe cost.
- Source: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_sobject_basic_info_get.htm

**`check_limits`** — `GET /limits` — **critical for backoff**
- No params. Response: object keyed by limit name → `{Max, Remaining}` (some nested, e.g. `PermissionSets.CreateCustom`). Key limits: `DailyApiRequests`, `DailyBulkApiBatches`, `DailyBulkV2QueryJobs`, `DailyAsyncApexExecutions`, `DataStorageMB`, `FileStorageMB`, `DailyStreamingApiEvents`, `HourlyAsyncReportRuns`.
- **Backoff strategy**: the MCP server should call this on startup and periodically (not per-call — that burns a call itself), track `DailyApiRequests.Remaining / Max`, and start throttling/queuing below ~10-15% remaining. Also read the `Sforce-Limit-Info` response header (see §2.9) on every real call — it's free (no extra request) and gives the same `api-usage=used/total` figure inline, which is the cheaper signal to drive backoff from in steady state.
- Source: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_limits.htm

**`get_record_count`** — `GET /limits/recordCount?sObjects={csv}`
- Query param: `sObjects` — comma list, optional (omit = all). Returns approximate row counts. Useful for planning bulk vs REST for large exports.
- Source: resources_list.htm

### 2.2 sObject CRUD by Id

**`get_record`** — `GET /sobjects/{obj}/{id}`
- Query param `fields` (comma list, optional — omit to get all readable fields, which is expensive; recommend the tool schema *require* a fields list to force intentional narrow reads).
- Headers: `If-Modified-Since`/`If-None-Match` supported (see §2.9).
- 200 + JSON record on success. 404 `NOT_FOUND` if ID invalid/no access. 400 `MALFORMED_ID`.
- Source: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_sobject_retrieve.htm

**`create_record`** — `POST /sobjects/{obj}`, body = JSON field map.
- Headers: `Content-Type: application/json`. Optional `Sforce-Auto-Assign` (bool, applies assignment rules for Lead/Case/Account), `Sforce-Duplicate-Rule-Header` (bypass/allow duplicate rules).
- 201 + `{id, success, errors}` on success. 400 with `errors[]` array (`REQUIRED_FIELD_MISSING`, `FIELD_CUSTOM_VALIDATION_EXCEPTION`, `DUPLICATE_VALUE`, `STRING_TOO_LONG`) on failure.
- Safety: additive, not idempotent — calling twice creates two records. Agent must not retry blindly on timeout without checking for the record first (idempotency key pattern recommended at the MCP layer: generate a client-side dedupe field or use an External ID upsert instead when retries are likely).
- Source: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_sobject_basic_info_post.htm

**`update_record`** — `PATCH /sobjects/{obj}/{id}`, body = partial JSON field map.
- **No response body on success** — 204 No Content. This is a common integration gotcha: callers expecting an echoed record must follow up with `get_record`.
- Headers: `If-Match`/`If-Unmodified-Since` for optimistic concurrency (ETag support currently limited to Account per docs — verify per-object before relying on it broadly).
- `_HttpMethod: PATCH` override header exists for HTTP clients that cannot issue PATCH verbs natively (send as POST with this header) — not needed for our server since it controls its own HTTP client, but worth supporting defensively if wrapping legacy transports.
- 204 on success; 400 `ENTITY_IS_DELETED`, `INVALID_FIELD`; 404 `NOT_FOUND`; 412 Precondition Failed if conditional header mismatch.
- Safety: destructive (overwrites field values) but idempotent — same PATCH body reapplied has same end-state. **Should require confirmation** for bulk/mass field updates or updates touching >1 record via any batched path.
- Source: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_sobject_retrieve.htm

**`delete_record`** — `DELETE /sobjects/{obj}/{id}`
- 204 on success (goes to Recycle Bin — recoverable for most orgs for 15 days, but treat as irreversible from the agent's perspective since undo isn't exposed via this endpoint set). 404 if already gone.
- **Must require explicit confirmation.** Idempotent in HTTP sense (repeat delete of gone record still effectively "deleted", though will 404 second time) — do not treat the 404 on retry as tool failure.
- Source: same page as above.

### 2.3 sObject Rows by External ID

**`get_record_by_external_id` / `upsert_record_by_external_id` / `create_record_with_external_id_seed` / `delete_record_by_external_id`** — all on `/sobjects/{obj}/{field}/{value}`
- `field` must be a field marked External ID (or Id itself, v37.0+) in the object's describe.
- **Upsert semantics (PATCH)** — the important one:
  - No match → creates new record → 201, `{id, success:true, created:true}`.
  - One match → updates → **200 with `{created:false}` on v46.0+, but 204 No Content with no body on v45.0 and earlier** — version-sensitive behavior the MCP server must branch on.
  - Multiple matches → **300 Multiple Choices**, record neither created nor updated, body lists ambiguous candidate URLs.
  - Optional query param `updateOnly=true` disables the create-on-no-match path (fails instead) — expose as a tool parameter for callers who want strict "update only" semantics without a separate PATCH-by-id call.
- Errors: 400 if the field named isn't actually configured as External ID; 400 on master-detail reparenting violations.
- Safety: upsert is DESTR, not fully idempotent (ambiguous-match 300 depends on data state); create/delete variants as their ID-based counterparts.
- Source: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_sobject_upsert.htm

### 2.4 Blob & Rich Text

**`get_blob_field`** — `GET /sobjects/{obj}/{id}/{blobField}` — binary response, `Content-Type` reflects stored MIME type. No JSON wrapper. For `Attachment.Body`, `ContentVersion.VersionData`, `Document.Body`, `EmailMessage.TextBody`(?) etc.
- **Truncation**: this can return arbitrarily large files. The tool must enforce a max byte size (reject or stream-summarize above e.g. 5-10MB) and never inline raw bytes into the model context — return a scratch-file path or a size/type summary instead.

**`get_rich_text_image`** — `GET /sobjects/{obj}/{id}/richTextImageFields/{field}/{contentReferenceId}` — same binary-handling caveat.

### 2.5 Change Feeds

**`get_deleted_records`** — `GET /sobjects/{obj}/deleted?start={ISO8601}&end={ISO8601}` (v29.0+)
- Returns `{deletedRecords: [{id, deletedDate}], earliestDateAvailable, latestDateCovered}`.
- Gotcha: backed by a rolling delete-log purged after records have sat >2h once a volume threshold is hit — **not a durable audit trail**; poll frequently if used for sync, don't rely on long look-back windows.

**`get_updated_records`** — `GET /sobjects/{obj}/updated?start=&end=` (v31.0+)
- Returns just `{ids: [...], latestDateCovered}` — no field data, caller must follow up with `get_record`/`collections_get_records`/SOQL for content.

### 2.6 Query & Search

**`soql_query`** — `GET /query?q={soql}`
- `q` (query, required, URL-encoded SOQL). Response: `{totalSize, done, records[], nextRecordsUrl?}`. Up to 2,000 rows per page (server may return fewer for wide/complex rows).
- **URL length gotcha**: GET request lines have practical limits (~2,000-16,000 chars depending on proxy/LB); Salesforce recommends switching to POST for long queries — hence tool #21.
- `Sforce-Query-Options: batchSize=N` request header can tune page size (max 2000).

**`soql_query_long`** — `POST /query`, body `{"q": "..."}` — identical semantics, for queries that would overflow a GET URL (large `IN (...)` lists, long field lists). The MCP server should auto-route to this when the encoded SOQL exceeds a safe threshold (~1900 chars) rather than exposing routing as a caller decision — but keep it as a distinct tool per the "split by mode" mandate, with the query builder helper choosing between them.

**`soql_query_more`** — `GET {nextRecordsUrl}` — opaque continuation URL from a prior `soql_query`/`soql_query_long` response; not a hand-built path. Tool takes the URL (or just the locator suffix) as input verbatim.

**`soql_query_all` / `soql_query_all_more`** — `/queryAll`, same shape as query/queryMore but result set includes soft-deleted (Recycle Bin) and archived records. Use for reconciliation/audit, not everyday reads (returns "noise" a normal agent query doesn't want).

**`explain_query_plan`** — `GET /query?explain={soql}` (Beta) — returns the optimizer's cardinality/cost estimate and which indexes would be used, without executing. Useful for the agent to self-check a SOQL before running it against a huge object.

**`sosl_search`** — `GET /search?q={sosl}` — free-text search across many objects at once (`FIND {term} IN ... RETURNING Account(...), Contact(...)`). Prefer this over SOQL when the target object is unknown/ambiguous.

**`parameterized_search` / `parameterized_search_advanced`** — simplified search without SOSL syntax; GET form takes params in the URL (search term, object list, fields), POST form accepts the same as a JSON body for cases with many objects/fields where the GET form would hit URL-length limits — mirrors the query/query_long split rationale.

**`get_search_scope_order` / `get_search_suggested_queries` / `get_search_suggested_article_titles` / `get_search_result_layouts`** — narrow UI-support endpoints; low priority (phase 2), included for completeness since they were listed on resources_list.htm.

Sources: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_query.htm ; https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_search.htm

### 2.7 Composite Family — the highest-leverage and highest-risk tool group

| Resource | Max sub-items | Transactional? | Cross-referencing? | Best for |
|---|---|---|---|---|
| `/composite` | 25 subrequests | Optional via `allOrNone` (whole request) | Yes — `@{refId.field}` | Sequential dependent calls (create parent, then use its ID) |
| `/composite/batch` | 25 subrequests | No (each subrequest its own txn) | No | Independent parallel-ish calls, minimize round trips |
| `/composite/graph` | Multiple named graphs, each up to (org-dependent) subrequest cap | Per-graph (each graph atomic) | Yes, within a graph | Multiple independent transactional units in one HTTP call |
| `/composite/tree/{obj}` | 200 records total, 5 levels deep | Atomic (whole tree) | Implicit parent→child by structure | Creating a record + its children in one shot |
| `/composite/sobjects` (Collections) | 200 records | Optional via `allOrNone` | No | Bulk create/update/upsert/delete/get of same-shape records, no dependency between them |

- **`composite_request`** (`POST /composite`): body `{allOrNone, compositeRequest:[{method,url,referenceId,body?,httpHeaders?}]}`. Response `{compositeResponse:[{httpStatusCode,body,referenceId,httpHeaders}]}`. Reference syntax `@{refId.fieldName}` (or `@{refId.id}`) lets subrequest N read a field from subrequest N-1's response. Whole thing counts as **1** API call against `DailyApiRequests`.
- **`composite_batch`** (`POST /composite/batch`): body `{batchRequests:[{method,url,richInput?}], haltOnError?}`. Subrequests are independent — no `@{}` referencing. If one fails, others still run unless `haltOnError:true`. This is the literal endpoint the project owner named as the floor requirement ("batch, up to 25 subrequests").
- **`composite_graph`** (`POST /composite/graph`): body `{graphs:[{graphId, compositeRequest:[...]}]}`. Each graph is its own atomic unit; multiple graphs run in one HTTP call. Response mirrors input shape with `graphResponse.compositeResponse[]` and `isSuccessful` per graph. v50.0+.
- **`create_records_with_children`** (sObject Tree, `POST /composite/tree/{obj}`): body has nested `records[]`, each with `attributes: {type, referenceId}` and child relationship arrays keyed by relationship name, each containing their own nested records. Response maps `referenceId → id` per created record, or per-record errors. **200 record cap across the whole tree, 5 levels of nesting max.** Insert-only — no upsert/update via tree.
- **Collections** (`/composite/sobjects`): GET takes `?ids=&fields=` (same-type only, ~800 ID practical cap before HTTP 414); POST/PATCH/DELETE take arrays in the body, 200-record cap, `allOrNone` flag, chunking internally in groups of up to 10 sub-batches when object types are mixed.

**Safety note for the whole family**: composite/batch/graph/tree/collections tools should be classified DESTR or IRREV based on the *worst* verb present in the payload (a batch containing even one DELETE subrequest is IRREV overall) — the MCP server must inspect the request body, not just the wrapper method, when deciding whether to require confirmation.

Sources: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_composite_composite.htm ; resources_composite_batch.htm ; resources_composite_graph.htm ; resources_composite_sobject_tree_flat.htm ; resources_composite_sobjects_collections_create.htm ; resources_composite_sobjects_collections_retrieve.htm ; resources_composite_sobjects_collections_delete.htm ; using_composite_resources.htm

### 2.8 Actions, Quick Actions, Layouts, List Views, Relationships

- **Invocable Actions** (`/actions/standard`, `/actions/custom`) — programmatic entry points into Flow, Chatter post, email, approval submission, etc. `describe_invocable_action` gives the input/output contract before `invoke_*` is called — always call describe first for unfamiliar actions since inputs vary per action type.
- **Quick Actions** (global `/quickActions/*` and object-scoped `/sobjects/{obj}/quickActions/*`) — UI-defined actions (e.g. "New Case", "Log a Call"); `get_..._default_values` pre-fills a form the way the Salesforce UI would, useful for the agent to know what a human would have seen.
- **Layouts** — five variants (page layouts, named layouts, compact layouts, approval layouts, multi-object compact layouts) exist because Salesforce has genuinely different layout systems for different UI surfaces; keep them as separate tools rather than one parameterized tool since the response shapes differ meaningfully.
- **List Views** — `list_list_views` → `get_list_view_results` is the common pair (discover then execute); `describe_list_view` exposes the underlying SOQL for power users/debugging.
- **sObject Relationships** (`/sobjects/{obj}/{id}/{relationshipName}`, v36.0+) — friendly-URL traversal, e.g. `/sobjects/Contact/003.../Account` to jump straight to the parent Account without a second query. GET/PATCH/DELETE on the *related* record (singular relationships only — doesn't replace SOQL for 1-to-many).

### 2.9 Headers, Status Codes, Conditional Requests (cross-cutting — apply to many tools above)

**Request headers**:
| Header | Purpose |
|---|---|
| `Authorization: Bearer {token}` | Required on every call except `list_api_versions`. |
| `Content-Type: application/json` | On all bodies. |
| `Sforce-Auto-Assign: TRUE/FALSE` | Apply assignment rules on create/update of Lead/Case/Account. |
| `Sforce-Duplicate-Rule-Header` | Control duplicate-rule enforcement/allow-save behavior on create/update. |
| `Sforce-Query-Options: batchSize=N` | Tune SOQL page size (≤2000). |
| `Sforce-Call-Options: client=...,defaultNamespace=...` | Client identification, default namespace for packaged orgs. |
| `Sforce-Mru: TRUE/FALSE` | Whether the call updates "Most Recently Used" (v60.0+). |
| `If-Match` / `If-None-Match` | ETag-based conditional GET/PATCH — currently documented as reliably supported on Account; verify per-object. |
| `If-Modified-Since` / `If-Unmodified-Since` | Time-based conditional GET/PATCH; broader support (sObject Rows, Describe, Describe Global, Invocable Actions). |
| `Accept-Encoding: gzip` | Response compression — worth always sending given describe/query payload sizes. |

**Response headers**: `Sforce-Limit-Info: api-usage=12/15000` (the cheap per-call rate-limit signal — parse this after *every* call instead of polling `/limits`), `Warning` (deprecated-version notices — surface these to the operator, don't just swallow them).

**HTTP status codes observed in docs**: 200, 201, 204, 300 (ambiguous external-ID upsert match), 304 (Not Modified — conditional GET), 400, 401, 403, 404, 405, 409, 410, 412 (Precondition Failed — conditional write lost the race), 414 (URI Too Long — GET query/collections-get with too many params, switch to POST/pagination), 415, 420 (rate-limited, some legacy paths), 428, 431, 500, 502, 503 (Chatter/Connect resources specifically return 503 on their *separate* per-user-per-hour rate limit, distinct from the main `DailyApiRequests` limit — relevant only if Connect API is ever added).

**Common documented/well-known error codes** (`errorCode` field in the 400/403/404 JSON body) the MCP server should special-case for good agent-facing messages:
| errorCode | Typical HTTP | Meaning |
|---|---|---|
| `INVALID_SESSION_ID` | 401 | Access token expired/revoked — trigger the auth refresh path, retry once. |
| `MALFORMED_QUERY` | 400 | Bad SOQL syntax — surface the query text back to the caller for correction. |
| `MALFORMED_ID` | 400 | ID string isn't a valid 15/18-char Salesforce ID. |
| `REQUIRED_FIELD_MISSING` | 400 | Create/update omitted a required field — body includes `fields[]` naming which. |
| `ENTITY_IS_DELETED` | 400 | Target record already deleted — treat as terminal, don't retry. |
| `NOT_FOUND` | 404 | Object/record/resource doesn't exist or no access — indistinguishable from "no access" by design (security through obscurity). |
| `DUPLICATE_VALUE` | 400 | Unique-field or duplicate-rule violation. |
| `FIELD_CUSTOM_VALIDATION_EXCEPTION` | 400 | Apex/declarative validation rule blocked the write — message text is admin-authored, pass through verbatim. |
| `INSUFFICIENT_ACCESS_ON_CROSS_REFERENCE_ENTITY` | 403 | FLS/sharing blocks access to a *related* record referenced by the write. |
| `STRING_TOO_LONG` | 400 | Field length exceeded. |
| `INVALID_FIELD` | 400 | Field name doesn't exist on the object (often a typo or wrong API name form, e.g. missing `__c`). |
| `INVALID_TYPE` | 400 | Value type mismatch for the field. |
| `REQUEST_LIMIT_EXCEEDED` | 403 | Org-wide API limit exhausted — this is the trigger condition for the `check_limits` backoff logic. |

Sources: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/headers.htm ; intro_rest_conditional_requests.htm ; errorcodes.htm

### 2.10 OpenAPI 3.0 Spec Generation for sObjects (Beta)

- Must be enabled per-org first: Setup → User Interface → "Salesforce Platform REST API, OpenAPI 3.0 Spec Generation (Beta)" (needs Modify All Data or Customize Application).
- **`generate_openapi_spec`** — `POST /async/specifications/oas3`, body selects resources (`"*"` for everything, or explicit `/sobjects/{obj}` / `/sobjects/{obj}/describe` selectors, optionally filtered by `sobjects.include: [...]`). Returns 202 + a locator ID and two URIs (status, results).
- **`get_openapi_spec_status`** — poll `GET .../oas3/{locatorId}` until generation completes.
- **`get_openapi_spec_result`** — `GET .../oas3/{locatorId}/results` → full OpenAPI 3.0.1 JSON document, valid for 48 hours.
- **Why this matters for us**: this is a legitimate path to auto-generate strongly-typed per-object schemas (request/response shapes, enums from picklists) instead of hand-maintaining them — but it's Beta (no production SLA, org must opt in, 48h TTL on results) and async (2-step poll), so v1 should NOT depend on it for correctness; treat it as an optional "schema refresh" utility a human/admin triggers occasionally, with `describe_object` remaining the source of truth the server code path relies on.
- Source: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/apexcode/openapi_beta.htm

### 2.11 What we're deliberately NOT covering (Connect REST API)

Connect REST API (`/services/data/vXX.X/connect/*`) is a *separate* API surface for Chatter feeds/posts/comments, Files, Groups, Topics, Notifications, and Experience Cloud (Communities) sites — plus industry-cloud extensions (Financial Services, Health Cloud, Manufacturing, Consumer Goods). It has its own auth model reuse (same OAuth tokens work) but a wholly different resource/response shape, its **own separate rate limit** (per-user-per-hour, distinct from `DailyApiRequests`, returns 503 when exceeded), and is oriented around social/collaboration objects rather than generic sObject CRUD. Breadth-only note: none of it is in our v1 tool set. If a future phase needs "post to Chatter" or "list files on a record," that's a new research pass against `https://developer.salesforce.com/docs/platform/connect-rest-api/guide/intro_what_is_chatter_connect.html`, not an extension of the sObject tool family documented here.

---

## 3. AUTHENTICATION

### 3.1 Flows

| Flow | User interaction? | Headless-suitable? | Status | Notes |
|---|---|---|---|---|
| **JWT Bearer** | No | **Yes — recommended** | Fully supported, no deprecation | Client signs a JWT (RS256) with a private key; Salesforce validates against an uploaded certificate on the Connected App / External Client App. No client secret transmitted per-call. Can run "pre-authorized" against a specific integration user without any login step ever happening. |
| **Client Credentials** | No | **Yes — recommended alternative** | Fully supported; **new apps should use External Client App, not legacy Connected App** (Connected App creation restricted as of Spring '26) | App exchanges `client_id`+`client_secret` for a token; acts as itself against a designated "run-as" integration user. Simpler to set up than JWT (no cert/key management) but the secret is a shared bearer credential — rotate it, store in a proper secret manager. |
| **Web Server (Authorization Code)** | Yes (browser redirect) | No | Supported | For apps acting on behalf of an interactively-logging-in human. Not applicable to an unattended MCP server. |
| **User-Agent / Device flows** | Yes | No | Supported (Device flow more relevant to CLI/TV-style login) | Same rationale — not for headless. |
| **Username-Password** | No (credentials in one POST) | Technically yes, but **do not use** | **Being retired.** Blocked by default on new orgs already; Salesforce is disabling it org-wide starting Winter '27, rolling out on sandboxes ~Aug 29 2026 and production the weekends of Aug 29, Oct 3, and Oct 10 2026 | Given today's date (2026-08-06), any integration built on this flow now would break within roughly 3-9 weeks of go-live. **Do not implement this flow at all** — go straight to JWT Bearer or Client Credentials. |

**Recommendation for salesforce-mcp**: use **JWT Bearer flow** as the default, with **Client Credentials** as a documented fallback for orgs/admins who'd rather not manage a certificate. Reasoning:
- Both are headless and avoid the imminently-retired username-password flow.
- JWT Bearer's private key never leaves the server that holds it (only a public cert is uploaded to Salesforce), which is a stronger security posture than a shared client secret sitting in config for Client Credentials.
- JWT Bearer supports acting "on behalf of" a specific integration user via the `sub` claim without that user ever typing a password, which maps cleanly onto least-privilege service-account design.
- Client Credentials is simpler for a quick-start / lower-security-bar deployment, so exposing it as an alternate configured auth mode (not a second code path per tool — just a pluggable token-acquisition strategy) covers both audiences cheaply.

### 3.2 JWT Bearer flow mechanics
1. Create a Connected App (or, per current guidance, an External Client App) with digital signatures enabled; upload the server's public certificate (`server.crt`).
2. Server signs a JWT with claims: `iss` = OAuth Consumer Key, `sub` = the Salesforce username to act as, `aud` = `https://login.salesforce.com` (production/My Domain) or `https://test.salesforce.com` (sandbox), `exp` = short-lived (commonly 3-5 min from now).
3. `POST https://{login-host}/services/oauth2/token`, `Content-Type: application/x-www-form-urlencoded`, body `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion={signed_jwt}`.
4. Response JSON: `access_token`, `instance_url` (the actual pod/My Domain host to call `/services/data/...` against — **never assume it equals the login host**), `id`, `token_type`, `scope`, `issued_at`.
5. No refresh token in this flow — when the access token expires (org session-timeout policy, typically hours), just re-run steps 2-4 to mint a new one. This makes token refresh trivial: "expired" and "get a new one" are the same code path, no refresh-token storage/rotation to manage.

### 3.3 Client Credentials flow mechanics
1. External Client App (preferred for new builds) or legacy Connected App with Client Credentials Flow enabled, and a designated "run-as" integration user configured on the app policy.
2. `POST https://{login-host}/services/oauth2/token`, body `grant_type=client_credentials&client_id={key}&client_secret={secret}`.
3. Response gives `access_token` + `instance_url` same as above. No refresh token — re-request on expiry, same as JWT.

### 3.4 Sandbox vs Production & My Domain
- Production/Dev orgs: `login.salesforce.com` (legacy) — but Salesforce increasingly requires the org's **My Domain** host (`https://{mydomain}.my.salesforce.com`) for the token endpoint too. Configure this per-deployment, don't hardcode `login.salesforce.com`.
- Sandboxes: `test.salesforce.com` or the sandbox's own My Domain host (`{mydomain}--{sandboxname}.sandbox.my.salesforce.com`).
- **`instance_url` from the token response is authoritative** for all subsequent `/services/data/...` calls — it can differ from the host you authenticated against (pod migrations, My Domain routing). Always use the returned value, never assume it matches the login host, and re-derive it on every fresh token acquisition rather than caching it long-term.

### 3.5 Token/session lifecycle for the MCP server
- No refresh tokens needed with either recommended flow — treat every token as short-lived and cheaply re-mintable. Cache the access token in memory with its known/assumed TTL, and reactively re-auth on the first `401 INVALID_SESSION_ID` from any call (retry once after refresh, don't loop).
- Do not persist access tokens to disk; do persist the JWT signing key / client secret in a proper secret store, not the repo or a flat config file.

Sources: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/intro_understanding_authentication.htm ; https://help.salesforce.com/s/articleView?id=sf.remoteaccess_oauth_jwt_flow.htm ; https://help.salesforce.com/s/articleView?id=xcloud.remoteaccess_oauth_client_credentials_flow.htm ; https://help.salesforce.com/s/articleView?id=release-notes.rn_security_unpw_flow_retirement.htm ; https://www.salesforceben.com/external-client-vs-connected-apps-comparing-salesforces-next-gen-integration/

---

## 4. TOOL COUNT & GROUPING PROBLEM

The full catalogue above lands at **~90 distinct tools** for core REST alone (before any Bulk/Tooling/Metadata/Connect expansion). This is well past the point where dumping every tool into one flat MCP tool list is good for an LLM caller:

**Problems with "expose everything, flat, always"**:
- Tool-selection accuracy degrades as the candidate list grows — an agent choosing among 90 similarly-named `describe_*`/`list_*` tools burns context on the tool manifest itself and is more likely to pick a near-miss (e.g. `get_record` vs `get_record_by_external_id` vs `collections_get_records`).
- Most sessions only ever touch 5-10 of these tools (CRUD + query + maybe composite). Paying the context cost of Knowledge-Article and Lightning-usage-metrics tool definitions on every single session is waste.
- Safety review is harder when destructive tools (delete, collections_delete, composite payloads that *might* contain a delete) sit undifferentiated next to read-only ones in one list.

**Recommended approach: namespaced, tiered progressive disclosure**, not one flat 90-tool manifest:

1. **Always-on core set (~15 tools)**: `list_objects`, `describe_object`, `get_object_basic_info`, `get_record`, `create_record`, `update_record`, `delete_record`, `soql_query`, `soql_query_more`, `sosl_search`, `check_limits`, `composite_batch`, `create_records_with_children`, `collections_create_records`, `collections_get_records`. This matches ~80% of realistic agent tasks and is small enough to reason about in one glance.
2. **Namespace/gate the rest behind categories** the agent (or the calling harness) opts into per-session or per-request, e.g. `sf.query.*` (long-query, queryAll, explain), `sf.composite.*` (graph, tree, collections-update/upsert/delete), `sf.metadata.*` (layouts, list views, actions, quick actions), `sf.admin.*` (password reset, workflow rules, approvals). This is the same shape as how Claude/MCP already handles tool-search-based deferred loading in this very session (`ToolSearch` over a big deferred-tool catalogue) — reuse that pattern: expose the ~15 core tools eagerly, and put the rest behind a `search_salesforce_tools(query)`-style discovery tool that surfaces matching tool schemas on demand.
3. **Group by safety class in the manifest metadata**, not just by function — so a harness-level policy ("never auto-approve IRREV tools") can filter/gate without per-tool special-casing.
4. **Collapse near-duplicate shapes where the LLM cost of an extra tool outweighs the endpoint-purity benefit** — e.g. the five layout-describe tools (2.8) are genuinely different response shapes and should stay separate; but the four Knowledge/data-category tools and six Lightning-usage-metric objects (which are really just `describe_object`+`soql_query` against specific object names) probably shouldn't be bespoke tools at all — they're just SOQL against named objects and add cardinality without adding capability. **Prune those from the tool list** and let `soql_query` cover them; keep bespoke tools only for endpoints with real behavioral divergence from generic sObject/query patterns.

Net recommendation: ship a **small always-on core**, implement **on-demand tool discovery/search** for the long tail (mirroring the ToolSearch pattern already proven effective in this environment), and **prune the "just SOQL a named object" pseudo-endpoints** out of the tool catalogue entirely — they don't need to be tools if `soql_query` + `describe_object` already cover them. This should bring the "tools an agent ever sees in one turn" number down from ~90 to ~15-25 typical, while the full ~90 (minus prunes, so realistically ~70) remains reachable.

---

## 5. v1 SCOPE RECOMMENDATION

### Ship in v1 (the always-on core + its natural extensions)
- **CRUD**: `list_objects`, `describe_object`, `get_object_basic_info`, `get_record`, `create_record`, `update_record`, `delete_record` — this is the non-negotiable floor; nothing else works without it.
- **External ID**: `get_record_by_external_id`, `upsert_record_by_external_id`, `delete_record_by_external_id` — upsert-by-external-ID is how most real integrations avoid duplicate-creation bugs; skipping it forces fragile "query then create-or-update" client-side logic.
- **Query/Search**: `soql_query`, `soql_query_more`, `soql_query_long`, `soql_query_all`, `sosl_search` — an agent that can't query flexibly is far less useful than raw CRUD suggests; this is core, not phase 2.
- **Composite**: `composite_batch` (explicitly named by the project owner), `composite_request`, `create_records_with_children`, `collections_create_records`, `collections_get_records`, `collections_update_records`, `collections_delete_records` — the multi-record efficiency wins here are large and the owner explicitly named batch/tree.
- **Limits**: `check_limits` — needed for the server's own backoff logic to function, not optional infrastructure.
- **Blob**: `get_blob_field` — common enough (attachments, files) to include, with strict size guardrails from day one.

**Reasoning**: this set covers "read anything, write anything, do it in bulk, don't blow the org's API budget" — the complete verbs an agent needs for the overwhelming majority of CRM automation tasks, while staying inside the ~20-25 tool range that keeps tool-selection sharp.

### Phase 2 (soon after v1, on demand)
- **Layouts & List Views** (2.8) — valuable for agents that need to mirror what a human sees in the UI (e.g. "what does the sales rep see on this record"), but not needed for pure data operations.
- **Actions & Quick Actions** — powerful (can trigger Flows, send email, log calls) but require a `describe_invocable_action` step to use safely; worth it once there's a concrete use case pulling for it, not speculatively.
- **Composite Graph, Collections Upsert, Explain Query Plan, Query-All variants** — real but comparatively niche; graph in particular only pays for itself once a caller needs *multiple independent atomic units* in one round trip, which is a fairly advanced usage pattern.
- **Change feeds** (`get_deleted_records`, `get_updated_records`) — mainly useful for building a sync/replication feature; add when that use case is actually requested.
- **Relationship traversal** (`get_related_records` etc.) — nice ergonomic sugar over SOQL, low urgency since SOQL already covers the same ground.

### Phase 3 / speculative / prune candidates
- **Search-support endpoints** (scope-order, suggested queries, suggested article titles, search result layouts) — UI-personalization plumbing, essentially never useful to a programmatic agent.
- **Knowledge/data-category, Lightning usage-metrics, App menu/tabs/theme** — as argued in §4, these are better served by `soql_query` against the named object than as bespoke tools; don't build them as tools, document them as "query these objects directly" instead.
- **Platform Event schema tools, OpenAPI spec generation** — legitimate but narrow (schema tooling for build-time codegen, not runtime agent operations); candidates for a separate "dev tooling" mode of the MCP server rather than the default agent-facing surface.
- **User password management, workflow rule triggering** — sensitive/administrative; gate behind an explicit admin-mode flag if ever added at all, given the blast radius of getting these wrong.
- **Everything in §2.11 (Connect REST API)** and Bulk API 2.0 / Metadata API / Tooling API / UI API — different API families entirely, each deserving their own research pass and probably their own MCP server or clearly separated tool namespace, not folded into this one.

---

## 6. Key gotchas checklist (cross-reference into §2 for detail)

1. Username-password OAuth flow is being retired **within weeks of this document's date** (Winter '27 rollout starts Aug 29 2026) — never implement it.
2. `update_record` (PATCH) returns **204 No Content**, not the updated record — callers must re-fetch if they need the new state.
3. External-ID upsert (PATCH) has **version-dependent response codes** (200 in v46+, 204 in v45-) for the "existing record updated" case — branch on configured API version.
4. External-ID upsert can return **300 Multiple Choices** if the "external ID" field isn't actually unique in the data — not just an error, a distinct partial-success-ish state to handle explicitly.
5. SOQL/Search GET requests have a **practical URL length ceiling (~2000 chars)** — long queries need the POST variant; the server should auto-detect and route rather than erroring.
6. Query pagination (`nextRecordsUrl`) is an **opaque continuation token**, not something to hand-construct — pass it through verbatim.
7. `composite`/`batch` cap at **25 subrequests**; `tree` caps at **200 records / 5 levels**; `collections` caps at **200 records** (~800-ID practical ceiling on GET by ID list before HTTP 414).
8. `composite/batch` subrequests are **individually transactional but the batch itself is not** — a failed subrequest #3 doesn't roll back #1-2.
9. `describe_object` responses are **large and should be truncated/cached** by default; it's also one of the few resources with decent conditional-request (If-Modified-Since) support — use it.
10. **`instance_url` from the OAuth token response is authoritative** and can differ from the login host — never hardcode or assume it equals `login.salesforce.com`/My Domain host used to authenticate.
11. Read `Sforce-Limit-Info` off every response for near-free rate-limit telemetry instead of polling `/limits` separately.
12. Blob-field responses are **raw binary with no size cap documented** — the MCP server must impose its own ceiling and never inline large payloads into model context.
