package intercept

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// fakeTypeSafe serves one canned probability map. Missing ids are omitted so a
// test can exercise an incomplete response.
func fakeTypeSafe(t *testing.T, probs map[string]float64) (JudgeConfig, *typesafeRequest) {
	t.Helper()
	var got typesafeRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/systemone" || r.Header.Get("Authorization") != "Bearer test-key" {
			t.Errorf("unexpected request %s auth=%q", r.URL.Path, r.Header.Get("Authorization"))
		}
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Fatalf("bad request body: %v", err)
		}
		out := map[string]any{}
		all := append(append([]typesafeRule{}, denyRules...), allowRules...)
		for _, r := range all {
			out[r.qid] = map[string]any{"type": "noul", "noul": 0.0}
		}
		for _, q := range []string{qProductionAssets, qIrreversible, qOwnershipUnknown, qBlastRadiusUnknown} {
			out[q] = map[string]any{"type": "noul", "noul": 0.0}
		}
		for id, p := range probs {
			out[id] = map[string]any{"type": "noul", "noul": p}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"model": "fake", "answers": out})
	}))
	t.Cleanup(srv.Close)
	return JudgeConfig{Backend: JudgeBackendTypeSafe, TypeSafeAPIKey: "test-key", TypeSafeModel: "fake", TypeSafeBaseURL: srv.URL}, &got
}

func reviewInput(command string) ReviewInput {
	return ReviewInput{Version: 4, Tool: "Bash", Arguments: json.RawMessage(`{"command":"` + command + `"}`)}
}

func TestTypesafeDecision(t *testing.T) {
	for _, tc := range []struct {
		name  string
		probs map[string]float64
		want  string
		rule  string
	}{
		{
			name:  "read-only is allow A5 even with unknown ownership",
			probs: map[string]float64{qReadOnly: 0.97, qIrreversible: 0.2},
			want:  "allow", rule: "A5",
		},
		{
			name:  "production data deletion is deny D4",
			probs: map[string]float64{qBusinessData: 0.98, qProductionAssets: 0.95, qIrreversible: 0.99},
			want:  "deny", rule: "D4",
		},
		{
			name:  "hazard without production assets falls through to ask",
			probs: map[string]float64{qBusinessData: 0.91, qProductionAssets: 0.2, qIrreversible: 0.9, qOwnershipUnknown: 0.8},
			want:  "ask",
		},
		{
			name:  "hazard on possibly-production is ask even with settled ownership",
			probs: map[string]float64{qAccountAvailability: 0.92, qProductionAssets: 0.45, qIrreversible: 0.95},
			want:  "ask",
		},
		{
			name:  "config change denies without the assets gate",
			probs: map[string]float64{qServiceConfig: 0.91, qProductionAssets: 0.3},
			want:  "deny", rule: "D3",
		},
		{
			name:  "highest hazard wins the rule id",
			probs: map[string]float64{qBusinessData: 0.72, qServiceAvailability: 0.88, qProductionAssets: 0.9},
			want:  "deny", rule: "D5",
		},
		{
			name:  "exploitation on assets is still allow when no deny rule fires",
			probs: map[string]float64{qExploitation: 0.93, qProductionAssets: 0.8},
			want:  "allow", rule: "A1",
		},
		{
			name:  "test artifact cleanup is allow A2",
			probs: map[string]float64{qTestArtifact: 0.9, qIrreversible: 0.8, qBusinessData: 0.15},
			want:  "allow", rule: "A2",
		},
		{
			name:  "irreversible write with settled ownership is default allow",
			probs: map[string]float64{qIrreversible: 0.9, qOwnershipUnknown: 0.1, qBlastRadiusUnknown: 0.1},
			want:  "allow", rule: "DEFAULT",
		},
		{
			name:  "irreversible write with unknown blast radius is ask",
			probs: map[string]float64{qIrreversible: 0.9, qBlastRadiusUnknown: 0.7},
			want:  "ask",
		},
		{
			name:  "nothing fires is default allow",
			probs: map[string]float64{},
			want:  "allow", rule: "DEFAULT",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			cfg, _ := fakeTypeSafe(t, tc.probs)
			d, err := typesafeDecision(context.Background(), cfg, reviewInput("rm -rf /var/www/html"))
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if d.Action != tc.want {
				t.Fatalf("action want %q got %q (%s)", tc.want, d.Action, d.Message)
			}
			if tc.rule != "" && !strings.Contains(d.Message, "Matched rule: "+tc.rule) {
				t.Fatalf("want rule %s in %q", tc.rule, d.Message)
			}
			if len([]rune(d.Message)) > 240 {
				t.Fatalf("message exceeds the 240-char contract: %d", len([]rune(d.Message)))
			}
			if !strings.HasPrefix(d.Message, "TypeSafe: Actual action: ") ||
				!strings.Contains(d.Message, "; Consequence if successful: ") ||
				!strings.Contains(d.Message, "; Matched rule: ") {
				t.Fatalf("message broke the verdict contract: %q", d.Message)
			}
		})
	}
}

// The battery must cover every rule so a missing answer cannot read as a no.
// The 240-character contract must never sever the rule id, which is the part
// operators scan for.
func TestTypesafeMessageKeepsRuleUnderLongArguments(t *testing.T) {
	in := ReviewInput{Tool: "Bash", Arguments: json.RawMessage(`{"command":"` + strings.Repeat("a", 2000) + `"}`)}
	msg := typesafeMessage(denyRules[3], in, "")
	if n := len([]rune(msg)); n > 240 {
		t.Fatalf("message exceeds 240 runes: %d", n)
	}
	if !strings.HasSuffix(msg, "Matched rule: D4") {
		t.Fatalf("rule id was clipped: %q", msg)
	}
	if !strings.Contains(msg, "; Consequence if successful: ") {
		t.Fatalf("consequence was clipped: %q", msg)
	}
}

func TestTypesafeRequestSendsWholeBattery(t *testing.T) {
	cfg, got := fakeTypeSafe(t, nil)

	if _, err := typesafeDecision(context.Background(), cfg, reviewInput("ls")); err != nil {
		t.Fatal(err)
	}
	for _, r := range append(append([]typesafeRule{}, denyRules...), allowRules...) {
		if _, ok := got.Questions[r.qid]; !ok {
			t.Fatalf("battery missing %s", r.qid)
		}
	}
	if got.State.Tool != "Bash" || string(got.State.Arguments) != `{"command":"ls"}` {
		t.Fatalf("state was not the review input: %+v", got.State)
	}
	if got.Model != "fake" {
		t.Fatalf("model not forwarded: %q", got.Model)
	}
}

func TestTypesafeMissingAnswerIsAnError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Only the read-only rule, nothing else.
		_ = json.NewEncoder(w).Encode(map[string]any{
			"model":   "fake",
			"answers": map[string]any{qReadOnly: map[string]any{"type": "noul", "noul": 0.9}},
		})
	}))
	defer srv.Close()
	cfg := JudgeConfig{TypeSafeAPIKey: "k", TypeSafeBaseURL: srv.URL}
	if _, err := typesafeDecision(context.Background(), cfg, reviewInput("ls")); err == nil {
		t.Fatal("missing answers must error, not read as zero")
	}
}

func TestTypesafeHTTPErrorAndNoKey(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "boom", http.StatusBadGateway)
	}))
	defer srv.Close()
	cfg := JudgeConfig{TypeSafeAPIKey: "k", TypeSafeBaseURL: srv.URL}
	if _, err := askTypesafe(context.Background(), cfg, reviewInput("ls")); err == nil || !strings.Contains(err.Error(), "502") {
		t.Fatalf("want HTTP status error, got %v", err)
	}
	if _, err := askTypesafe(context.Background(), JudgeConfig{}, reviewInput("ls")); err == nil {
		t.Fatal("missing key must error")
	}
}
