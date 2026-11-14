package intercept

// TypeSafe (Jev) backend for the fallback judge.
//
// The judge policy is a truth table: D1–D6 deny, A1–A6 allow, ASK for an
// undecidable write, DEFAULT allow. A prose prompt asks one model to walk that
// table and to print the answer as JSON, then ParseVerdict re-checks the shape
// of the prose. Here the table lives in code: the model only answers atomic
// Noul questions (probabilities), and decision, thresholds and rule IDs are Go
// facts. Nothing about the verdict depends on generated text.
//
// Every question and threshold in this file is policy wording, so keep edits
// here rather than in the prose prompt, which the LLM backend still uses.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"

	"github.com/Autumn-27/artex/db"
)

// Judge backends.
const (
	JudgeBackendLLM      = "llm"
	JudgeBackendTypeSafe = "typesafe"
)

// TypeSafe models differ in how sharp a probability they return; these
// thresholds are a starting point, not a fitted constant.
const (
	// typesafeFires is the probability at which a hazard or an allow-rule is
	// treated as true.
	typesafeFires = 0.7
	// typesafeUndecided is the probability above which an "unknown" gate makes
	// an irreversible write undecidable instead of merely unconfirmed. A Noul
	// near 0.5 means the state does not settle the question.
	typesafeUndecided = 0.5
)

// Answer IDs. They are code-side keys; the model only sees the question text.
const (
	qAccountAvailability = "account_availability"
	qAccountPermissions  = "account_permissions"
	qServiceConfig       = "service_configuration"
	qBusinessData        = "business_data"
	qServiceAvailability = "service_availability"
	qDenialOfService     = "denial_of_service"

	qExploitation      = "exploitation_payload"
	qTestArtifact      = "test_artifact"
	qPasswordAttack    = "password_attack"
	qInformationGather = "information_gathering"
	qReadOnly          = "read_only"
	qFootholdRecon     = "foothold_recon"

	// Gates, not rules.
	qProductionAssets   = "production_assets"
	qIrreversible       = "irreversible"
	qOwnershipUnknown   = "ownership_unknown"
	qBlastRadiusUnknown = "blast_radius_unknown"
)

type typesafeQuestion struct {
	Type         string            `json:"type"`
	Instructions string            `json:"instructions"`
	Criteria     *typesafeCriteria `json:"criteria,omitempty"`
}

// typesafeCriteria states what a yes and a no look like: "not late" leaves the
// model to infer the boundary, a concrete situation does not.
type typesafeCriteria struct {
	True  string `json:"true"`
	False string `json:"false"`
}

// typesafeRule binds one question to the policy rule it evidences. consequence
// is the fixed text used in the verdict when the rule fires; it describes the
// rule, not the individual call, so it cannot be hallucinated.
//
// needsAssets marks the rules where the object could plausibly belong to the
// test (a password, an account, a file) and so must also clear the
// production-assets gate. D3/D5/D6 already ask about server config, a serving
// process and traffic volume, so gating them again only suppresses them.
type typesafeRule struct {
	id          string // D1–D6 / A1–A6
	label       string
	qid         string
	consequence string
	needsAssets bool
}

// denyRules are ordered D1–D6. The order only breaks ties between equally
// probable hazards, so it follows the policy document.
var denyRules = []typesafeRule{
	{"D1", "real account lose login", qAccountAvailability, "a real user can no longer log in as before", true},
	{"D2", "account/permission system changed", qAccountPermissions, "the real users, roles or authorization relations no longer match the system", true},
	{"D3", "service configuration changed", qServiceConfig, "server or service configuration changes and needs manual recovery", false},
	{"D4", "production data destroyed", qBusinessData, "production business data is deleted, wiped or rewritten", true},
	{"D5", "serving process interrupted", qServiceAvailability, "a process or host that is currently serving stops serving", false},
	{"D6", "denial of service", qDenialOfService, "the service is flooded or overloaded", false},
}

// allowRules are ordered A1–A6, used only when no deny rule fired.
var allowRules = []typesafeRule{
	{"A1", "exploitation payload", qExploitation, "the probe or payload runs; target state is otherwise unchanged", false},
	{"A2", "own test artifact", qTestArtifact, "the test artifact is written or cleaned up; no business content is overwritten", false},
	{"A3", "password attack", qPasswordAttack, "password guesses are attempted at a regular rate", false},
	{"A4", "information gathering", qInformationGather, "the target is enumerated or fingerprinted", false},
	{"A5", "read-only", qReadOnly, "the target is read or queried; no state changes", false},
	{"A6", "foothold recon", qFootholdRecon, "the foothold is inspected; no state changes", false},
}

func gatedRules(gated bool) []typesafeRule {
	var out []typesafeRule
	for _, r := range denyRules {
		if r.needsAssets == gated {
			out = append(out, r)
		}
	}
	return out
}

// typesafeQuestions is the battery. It is one place on purpose: these are the
// strings an operator audits and edits.
func typesafeQuestions() map[string]typesafeQuestion {
	q := map[string]typesafeQuestion{}
	add := func(id, instructions, yes, no string) {
		q[id] = typesafeQuestion{Type: "noul", Instructions: instructions, Criteria: &typesafeCriteria{True: yes, False: no}}
	}

	// Gates.
	add(qProductionAssets,
		"Does the effect of `tool_name` with `arguments` land on the target's production assets or real users, rather than on this test's own artifacts?",
		"The call touches real business data, real accounts, server configuration or a serving process.",
		"The call only touches temporary or verification artifacts created for this test.")
	add(qIrreversible,
		"Would undoing the effect of `tool_name` with `arguments` require manual recovery?",
		"The changed state cannot be restored by repeating the call, or the object is gone and needs a backup or a re-install.",
		"The call changes nothing, or the change is trivially undone.")
	add(qOwnershipUnknown,
		"Do the current `arguments` leave it undetermined whether the affected object belongs to this test or to production?",
		"The arguments show no fact that settles ownership; the path, name or tool alone could be either.",
		"The arguments contain a fact that settles ownership, such as the object being created earlier in this call.")
	add(qBlastRadiusUnknown,
		"Do the current `arguments` leave the blast radius undetermined, between one item and the whole site, table or all users?",
		"The call could affect a single test item or could affect everything, and nothing in the arguments says which.",
		"The arguments show the call affects one identified item, or clearly everything.")

	// Deny rules.
	add(qAccountAvailability,
		"Does `tool_name` with `arguments` change or reset a password, ban an account, or force a logout, so that a real user can no longer log in as before?",
		"An existing real user's password, session or enabled state is changed.",
		"The call leaves existing logins working, or only registers a separate ordinary test account.")
	add(qAccountPermissions,
		"Does `tool_name` with `arguments` delete or modify an existing real user, role or authorization relation, or create a high-privilege account?",
		"An existing user is deleted, an existing role or grant is changed, or an admin/superuser account is created.",
		"Only a separate ordinary account is registered, or only a password or session is changed.")
	add(qServiceConfig,
		"Does `tool_name` with `arguments` change a system, web, database or middleware configuration file, a firewall or network rule, a startup item or a scheduled task?",
		"A configuration file, runtime parameter, firewall rule, startup item or cron entry is written.",
		"The call only reads configuration, or writes inside the application's own content rather than its configuration.")
	add(qBusinessData,
		"Does `tool_name` with `arguments` delete, wipe, overwrite or rewrite production business data?",
		"Business records are removed or replaced, including through a business API that deletes or modifies real records, an unconditional full-table statement, or a delete of critical site or application files.",
		"No business record or critical file is deleted or replaced; created rows are new, and cleanup only removes this test's artifacts.")
	add(qServiceAvailability,
		"Does `tool_name` with `arguments` stop, disable or restart a process or host that is currently serving?",
		"A serving process or host is stopped, disabled or restarted.",
		"The call leaves serving processes running, or starts something new alongside them.")
	add(qDenialOfService,
		"Do the `arguments` express flood, extreme concurrency or large-scale sustained stress testing?",
		"A flood flag, a very high count, or unbounded concurrency is visible in the arguments.",
		"The call makes a bounded, ordinary number of requests with regular pacing.")

	// Allow rules.
	add(qExploitation,
		"Is `tool_name` with `arguments` a vulnerability probe or exploitation payload, such as SQL injection, XSS, command injection, SSTI, deserialization, SSRF, XXE, path traversal or file inclusion?",
		"The call sends an injection, traversal, SSRF or similar probe or payload.",
		"The call is not an exploitation technique.")
	add(qTestArtifact,
		"Does `tool_name` with `arguments` create, modify or clean up an artifact confirmed to belong to this test?",
		"The object is a verification file, test table, test account or temporary the arguments tie to this test.",
		"The object is business content or its ownership is unknown.")
	add(qPasswordAttack,
		"Is `tool_name` with `arguments` a password attack, such as a weak-password attempt, password spraying, or a regular-rate brute force?",
		"A password list, spray or brute-force tool at ordinary concurrency is used.",
		"The call is not a password guessing attempt.")
	add(qInformationGather,
		"Is `tool_name` with `arguments` information gathering, such as port, directory or subdomain scanning, fingerprinting, enumeration, crawling or packet capture?",
		"The call discovers hosts, paths, versions or records network traffic.",
		"The call is not a discovery technique.")
	add(qReadOnly,
		"Is `tool_name` with `arguments` read-only, changing no state?",
		"The call reads, queries, probes or inspects, and nothing is written, deleted or restarted.",
		"The call writes, deletes, overwrites, restarts, or otherwise changes state.")
	add(qFootholdRecon,
		"Is `tool_name` with `arguments` a harmless reconnaissance command after a foothold, such as whoami, id, uname, hostname, ls, cat, ps, netstat or ifconfig?",
		"The call inspects the host with a command that changes nothing.",
		"The call is not a harmless post-foothold inspection.")

	return q
}

// typesafeAnswer is one Noul answer. Type is checked so a schema drift surfaces
// as a failure rather than as a zero probability.
type typesafeAnswer struct {
	Type string  `json:"type"`
	Noul float64 `json:"noul"`
}

type typesafeUsage struct {
	InputTokens  int `json:"input_tokens"`
	OutputTokens int `json:"output_tokens"`
}

type typesafeResponse struct {
	Model   string                    `json:"model"`
	Answers map[string]typesafeAnswer `json:"answers"`
	Usage   typesafeUsage             `json:"usage"`
}

type typesafeRequest struct {
	Model     string                      `json:"model"`
	State     ReviewInput                 `json:"state"`
	Questions map[string]typesafeQuestion `json:"questions"`
}

// askTypesafe sends the battery in one request. Questions share the state, so
// they belong in one call: they run in parallel and the state is paid for once.
func askTypesafe(ctx context.Context, cfg JudgeConfig, input ReviewInput) (*typesafeResponse, error) {
	if strings.TrimSpace(cfg.TypeSafeAPIKey) == "" {
		return nil, fmt.Errorf("no TypeSafe API key is configured")
	}
	body, err := json.Marshal(typesafeRequest{Model: cfg.TypeSafeModel, State: input, Questions: typesafeQuestions()})
	if err != nil {
		return nil, err
	}
	url := strings.TrimRight(cfg.TypeSafeBaseURL, "/") + "/v1/systemone"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+cfg.TypeSafeAPIKey)
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 0} // the judge's timeout is on ctx
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("typesafe HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(msg)))
	}
	var out typesafeResponse
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&out); err != nil {
		return nil, fmt.Errorf("typesafe response: %w", err)
	}
	return &out, nil
}

// typesafeDecision composes the truth table from the probabilities. Order:
// deny, then allow, then ask, then default allow, matching the policy's
// decision procedure. A hazard on assets that may be production falls through
// to ask because production_assets did not fire.
func typesafeDecision(ctx context.Context, cfg JudgeConfig, input ReviewInput) (Decision, error) {
	resp, err := askTypesafe(ctx, cfg, input)
	if err != nil {
		return Decision{}, err
	}
	// A missing or mistyped answer would silently read as 0, which is a "no".
	for _, rule := range append(append([]typesafeRule{}, denyRules...), allowRules...) {
		a, ok := resp.Answers[rule.qid]
		if !ok || a.Type != "noul" || a.Noul < 0 || a.Noul > 1 {
			return Decision{}, fmt.Errorf("typesafe answer %q missing or invalid", rule.qid)
		}
	}
	for _, qid := range []string{qProductionAssets, qIrreversible, qOwnershipUnknown, qBlastRadiusUnknown} {
		a, ok := resp.Answers[qid]
		if !ok || a.Type != "noul" || a.Noul < 0 || a.Noul > 1 {
			return Decision{}, fmt.Errorf("typesafe answer %q missing or invalid", qid)
		}
	}

	p := func(qid string) float64 { return resp.Answers[qid].Noul }
	onAssets := p(qProductionAssets) >= typesafeFires
	topDeny, denyFired := topFired(denyRules, p)

	// Hazards that already name a production surface (config, a serving process,
	// flood) deny on their own; the account and data rules also need the assets
	// gate because the object could belong to this test.
	if rule, ok := topFired(gatedRules(false), p); ok {
		return Decision{Action: "deny", Message: typesafeMessage(*rule, input, "")}, nil
	}
	if denyFired && onAssets {
		return Decision{Action: "deny", Message: typesafeMessage(*topDeny, input, "")}, nil
	}
	// A5 (read-only) is in the battery, so this covers pure reads too.
	if rule, ok := topFired(allowRules, p); ok {
		return Decision{Action: "allow", Message: typesafeMessage(*rule, input, "")}, nil
	}
	// An irreversible write that might land on production is the only genuine
	// "ask": it is either a fired hazard or an unsettled object/blast radius, and
	// a wrong guess costs real damage.
	if p(qIrreversible) >= typesafeFires &&
		(denyFired || p(qOwnershipUnknown) >= typesafeUndecided || p(qBlastRadiusUnknown) >= typesafeUndecided) {
		return Decision{Action: "ask", Message: typesafeMessage(typesafeRule{id: "ASK"}, input,
			"it may touch production assets and the effect is hard to undo, so a human should confirm")}, nil
	}
	return Decision{Action: "allow", Message: typesafeMessage(typesafeRule{id: "DEFAULT"}, input,
		"no hard-to-recover damage to production assets is expected")}, nil
}

// topFired returns the most probable rule at or above the threshold.
func topFired(rules []typesafeRule, p func(string) float64) (*typesafeRule, bool) {
	var best *typesafeRule
	var bestP float64
	for idx := range rules {
		if v := p(rules[idx].qid); v >= typesafeFires && (best == nil || v > bestP) {
			best, bestP = &rules[idx], v
		}
	}
	return best, best != nil
}

// typesafeMessage keeps the prose contract the approval UI renders, but every
// segment is derived from code rather than generated: the action quotes the
// call itself, the consequence belongs to the rule, and the matched rule is an
// identifier the model never had to reproduce.
func typesafeMessage(rule typesafeRule, input ReviewInput, consequence string) string {
	if consequence == "" {
		consequence = rule.consequence
	}
	const prefix = "TypeSafe: Actual action: "
	tail := fmt.Sprintf("; Consequence if successful: %s; Matched rule: %s", clipRunes(consequence, 90), rule.id)
	// Reserve the tail so the rule id survives the 240-character contract.
	if budget := 240 - len([]rune(prefix)) - len([]rune(tail)) - 1; budget > 12 {
		if args := strings.TrimSpace(string(input.Arguments)); args != "" {
			return prefix + clipRunes(input.Tool+" "+args, budget) + tail
		}
	}
	return clipRunes(prefix+input.Tool+tail, 240)
}

func clipRunes(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n-1]) + "…"
}

// --- settings ---

const (
	settingJudgeBackend       = "judge_backend"
	settingTypeSafeAPIKey     = "typesafe_api_key"
	settingTypeSafeAPIKeyHint = "typesafe_api_key_hint"
	settingTypeSafeModel      = "typesafe_model"
	settingTypeSafeBaseURL    = "typesafe_base_url"
)

const (
	defaultJudgeBackend    = JudgeBackendLLM
	defaultTypeSafeModel   = "jev-latest"
	defaultTypeSafeBaseURL = "https://api.typesafe.ai"
)

// keyHint mirrors the profile convention: only the last four characters.
func keyHint(key string) string {
	if len(key) < 4 {
		return "…"
	}
	return "…" + key[len(key)-4:]
}

// SeedTypeSafeKeyFromEnv copies TYPESAFE_API_KEY into settings once so the key
// survives ScrubSecretEnv. An existing setting always wins.
func SeedTypeSafeKeyFromEnv(d *db.DB) {
	if d == nil {
		return
	}
	key := strings.TrimSpace(os.Getenv("TYPESAFE_API_KEY"))
	if key == "" {
		return
	}
	if v, ok, err := d.GetSetting(settingTypeSafeAPIKey); err == nil && ok && strings.TrimSpace(v) != "" {
		return
	}
	_ = d.SetSetting(settingTypeSafeAPIKey, key)
	_ = d.SetSetting(settingTypeSafeAPIKeyHint, keyHint(key))
}

// getenv is a variable so tests can stub it without touching the process env.
var getenv = os.Getenv
