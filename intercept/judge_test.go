package intercept

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/Autumn-27/artex/db"
)

// openJudgeTestDB skips unless the suite is running with a database.
func openJudgeTestDB(t *testing.T) *db.DB {
	t.Helper()
	dsn, _, err := db.DSN()
	if err != nil {
		t.Skip("no test database configured")
	}
	d, err := db.Open(dsn)
	if err != nil {
		t.Fatalf("open test database: %v", err)
	}
	t.Cleanup(func() { _ = d.Close() })
	return d
}

func setJudgeSettings(t *testing.T, d *db.DB, backend, baseURL string) {
	t.Helper()
	for k, v := range map[string]string{
		settingJudgeEnabled:    "true",
		settingJudgeBackend:    backend,
		settingTypeSafeAPIKey:  "test-key",
		settingTypeSafeBaseURL: baseURL,
		settingTypeSafeModel:   "fake",
		settingJudgeFailAction: "deny",
	} {
		if err := d.SetSetting(k, v); err != nil {
			t.Fatal(err)
		}
	}
}

// Judge must dispatch to TypeSafe without a wired LLM reviewer, and a failed
// TypeSafe call must follow the fail action instead of becoming an answer.
func TestJudgeTypeSafeBackend(t *testing.T) {
	d := openJudgeTestDB(t)
	ic := New(d)

	// No reviewer: the LLM backend would stay inert, TypeSafe must still run.
	if err := d.SetBool(settingJudgeEnabled, true); err != nil {
		t.Fatal(err)
	}
	if err := d.SetSetting(settingJudgeBackend, JudgeBackendLLM); err != nil {
		t.Fatal(err)
	}
	if _, ran := ic.Judge(context.Background(), "Bash", json.RawMessage(`{"command":"ls"}`)); ran {
		t.Fatal("LLM backend without a reviewer must not produce a verdict")
	}

	probs := map[string]float64{qReadOnly: 0.96}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		answers := map[string]any{}
		all := append(append([]typesafeRule{}, denyRules...), allowRules...)
		for _, rule := range all {
			answers[rule.qid] = map[string]any{"type": "noul", "noul": 0.0}
		}
		for _, q := range []string{qProductionAssets, qIrreversible, qOwnershipUnknown, qBlastRadiusUnknown} {
			answers[q] = map[string]any{"type": "noul", "noul": 0.0}
		}
		for id, p := range probs {
			answers[id] = map[string]any{"type": "noul", "noul": p}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"model": "fake", "answers": answers})
	}))
	defer srv.Close()
	setJudgeSettings(t, d, JudgeBackendTypeSafe, srv.URL)

	d1, ran := ic.Judge(context.Background(), "Bash", json.RawMessage(`{"command":"cat /etc/passwd"}`))
	if !ran || d1.Action != "allow" {
		t.Fatalf("want an allow verdict, got ran=%v %+v", ran, d1)
	}
	if d1.ModelFallback || len(d1.ModelInput) == 0 {
		t.Fatalf("verdict should carry the reviewed input, got %+v", d1)
	}

	// Point at a dead endpoint: the call fails and the fail action (deny) applies.
	if err := d.SetSetting(settingTypeSafeBaseURL, "http://127.0.0.1:1"); err != nil {
		t.Fatal(err)
	}
	d2, ran := ic.Judge(context.Background(), "Bash", json.RawMessage(`{"command":"ls"}`))
	if !ran || d2.Action != "deny" || !d2.ModelFallback {
		t.Fatalf("want fail-action deny, got ran=%v %+v", ran, d2)
	}
}
