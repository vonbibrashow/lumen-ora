//! Lumen Ora — Policy Engine
//!
//! Intercepts AI tool calls and enforces security policies before execution.
//! Every tool call goes through `PolicyEngine::evaluate` and receives a
//! `PolicyDecision` (Allow / Deny / RequireConfirmation) before the host
//! shell or inference bridge is permitted to run it.

use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tracing::{debug, info, warn};

// ---------------------------------------------------------------------------
// Core data types
// ---------------------------------------------------------------------------

/// The action a rule takes when it matches.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "action", content = "payload")]
pub enum RuleAction {
    Allow,
    Deny,
    RequireConfirmation,
}

/// A single security policy rule.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyRule {
    /// Unique identifier for this rule (e.g. "path-traversal-deny").
    pub id: String,
    /// Human-readable description shown in audit logs and confirmation dialogs.
    pub description: String,
    /// The action to take when this rule matches a tool call.
    pub action: RuleAction,
    /// Priority — lower numbers are evaluated first. First match wins.
    pub priority: u32,
}

/// A tool call originating from the AI model, captured before execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCall {
    /// The name of the tool (e.g. "write_file", "run_command").
    pub tool_name: String,
    /// Raw parameters as a JSON object. The policy engine inspects these.
    pub parameters: serde_json::Value,
    /// Session / conversation context (user id, session id, etc.).
    pub context: HashMap<String, String>,
}

impl ToolCall {
    pub fn new(tool_name: impl Into<String>, parameters: serde_json::Value) -> Self {
        Self {
            tool_name: tool_name.into(),
            parameters,
            context: HashMap::new(),
        }
    }

    /// Convenience: get a string parameter by key.
    pub fn param_str(&self, key: &str) -> Option<&str> {
        self.parameters.get(key)?.as_str()
    }

    /// Convenience: get a JSON array parameter by key.
    pub fn param_array(&self, key: &str) -> Option<&Vec<serde_json::Value>> {
        self.parameters.get(key)?.as_array()
    }
}

/// The decision returned after evaluating a tool call against all rules.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "decision", content = "detail")]
pub enum PolicyDecision {
    /// The tool call is permitted — proceed.
    Allow,
    /// The tool call is blocked. `reason` is logged and returned to the model.
    Deny { reason: String },
    /// A human must confirm before the tool call proceeds.
    RequireConfirmation { message: String },
}

/// Audit record written to the append-only log for every evaluated call.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditEntry {
    pub timestamp_ms: u128,
    pub tool_call: ToolCall,
    pub decision: PolicyDecision,
    /// Which rule triggered the decision, if any.
    pub matched_rule_id: Option<String>,
}

// ---------------------------------------------------------------------------
// Policy Engine
// ---------------------------------------------------------------------------

/// The policy engine. Holds an ordered list of rules and evaluates tool calls.
///
/// Rules are evaluated in ascending `priority` order. The first rule that
/// matches determines the decision. If no rule matches, the call is Allowed
/// (fail-open by default; override with `default_deny`).
pub struct PolicyEngine {
    rules: Vec<PolicyRule>,
    /// When true, calls that match no rule are Denied instead of Allowed.
    pub default_deny: bool,
}

impl PolicyEngine {
    /// Construct the engine with the built-in starter rule set.
    pub fn with_default_rules() -> Self {
        let mut engine = Self {
            rules: Vec::new(),
            default_deny: false,
        };
        engine.add_starter_rules();
        engine
    }

    /// Add a rule to the engine (inserted in priority order).
    pub fn add_rule(&mut self, rule: PolicyRule) {
        self.rules.push(rule);
        self.rules.sort_by_key(|r| r.priority);
    }

    /// Evaluate a tool call and return a decision.
    pub fn evaluate(&self, tool_call: &ToolCall) -> (PolicyDecision, Option<String>) {
        debug!(tool = %tool_call.tool_name, "evaluating tool call");

        for rule in &self.rules {
            if let Some(decision) = self.apply_rule(rule, tool_call) {
                info!(
                    rule_id = %rule.id,
                    tool = %tool_call.tool_name,
                    decision = ?decision,
                    "rule matched"
                );
                return (decision, Some(rule.id.clone()));
            }
        }

        // No rule matched — apply default.
        let decision = if self.default_deny {
            warn!(tool = %tool_call.tool_name, "no rule matched — default deny");
            PolicyDecision::Deny {
                reason: "No policy rule permits this tool call.".to_string(),
            }
        } else {
            debug!(tool = %tool_call.tool_name, "no rule matched — default allow");
            PolicyDecision::Allow
        };

        (decision, None)
    }

    /// Evaluate and build a full audit entry (populates timestamp).
    pub fn evaluate_with_audit(&self, tool_call: ToolCall) -> AuditEntry {
        let (decision, matched_rule_id) = self.evaluate(&tool_call);
        let timestamp_ms = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        AuditEntry {
            timestamp_ms,
            tool_call,
            decision,
            matched_rule_id,
        }
    }

    // -----------------------------------------------------------------------
    // Rule matching logic
    // -----------------------------------------------------------------------

    fn apply_rule(&self, rule: &PolicyRule, call: &ToolCall) -> Option<PolicyDecision> {
        match rule.id.as_str() {
            "path-traversal-deny" => self.rule_path_traversal(rule, call),
            "write-outside-home-deny" => self.rule_write_outside_home(rule, call),
            "raw-ip-network-confirm" => self.rule_raw_ip_network(rule, call),
            "tmp-exec-deny" => self.rule_tmp_exec(rule, call),
            "bulk-delete-confirm" => self.rule_bulk_delete(rule, call),
            _ => None,
        }
    }

    // Rule 1: Deny any tool call with a path parameter containing ".."
    fn rule_path_traversal(&self, rule: &PolicyRule, call: &ToolCall) -> Option<PolicyDecision> {
        let path_params = ["path", "src", "dst", "source", "destination", "file"];
        for param in &path_params {
            if let Some(v) = call.parameters.get(param).and_then(|v| v.as_str()) {
                if v.contains("..") {
                    return Some(PolicyDecision::Deny {
                        reason: format!(
                            "[{}] Path traversal detected in parameter '{}': {:?}",
                            rule.id, param, v
                        ),
                    });
                }
            }
        }
        // Also check nested paths inside args arrays
        if let Some(args) = call.param_array("args") {
            for arg in args {
                if let Some(s) = arg.as_str() {
                    if s.contains("..") {
                        return Some(PolicyDecision::Deny {
                            reason: format!(
                                "[{}] Path traversal detected in args: {:?}",
                                rule.id, s
                            ),
                        });
                    }
                }
            }
        }
        None
    }

    // Rule 2: Deny file writes outside the user's home directory.
    fn rule_write_outside_home(&self, rule: &PolicyRule, call: &ToolCall) -> Option<PolicyDecision> {
        if call.tool_name != "write_file" {
            return None;
        }
        let path = call.param_str("path")?;
        let home = call
            .context
            .get("home_dir")
            .map(String::as_str)
            .unwrap_or("/home");

        // Explicit grant overrides the rule.
        if call.context.get("grant_write_outside_home").map(String::as_str) == Some("true") {
            return None;
        }

        let normalized = path.replace('\\', "/");
        let home_norm = home.replace('\\', "/");

        if !normalized.starts_with(&home_norm) {
            return Some(PolicyDecision::Deny {
                reason: format!(
                    "[{}] write_file target '{}' is outside home directory '{}'. \
                     Set context.grant_write_outside_home=true to override.",
                    rule.id, path, home
                ),
            });
        }
        None
    }

    // Rule 3: RequireConfirmation when a network tool targets a raw IP address.
    fn rule_raw_ip_network(&self, rule: &PolicyRule, call: &ToolCall) -> Option<PolicyDecision> {
        let network_tools = ["http_request", "connect", "fetch", "search_web", "tcp_connect"];
        if !network_tools.contains(&call.tool_name.as_str()) {
            return None;
        }
        // Match IPv4 or IPv6 literals anywhere in url/host parameters.
        let ipv4 = Regex::new(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b").unwrap();
        let ipv6 = Regex::new(r"\[?[0-9a-fA-F:]{2,39}\]?").unwrap();

        let url_params = ["url", "host", "address", "endpoint"];
        for param in &url_params {
            if let Some(v) = call.parameters.get(param).and_then(|v| v.as_str()) {
                if ipv4.is_match(v) || ipv6.is_match(v) {
                    return Some(PolicyDecision::RequireConfirmation {
                        message: format!(
                            "[{}] Tool '{}' is targeting a raw IP address: '{}'. \
                             Direct IP connections may indicate C2 traffic. Approve?",
                            rule.id, call.tool_name, v
                        ),
                    });
                }
            }
        }
        None
    }

    // Rule 4: Deny execution of files located in /tmp.
    fn rule_tmp_exec(&self, rule: &PolicyRule, call: &ToolCall) -> Option<PolicyDecision> {
        let exec_tools = ["run_command", "exec", "execute", "spawn"];
        if !exec_tools.contains(&call.tool_name.as_str()) {
            return None;
        }
        let command = call.param_str("command")?;
        let normalized = command.replace('\\', "/");
        if normalized.starts_with("/tmp/") || normalized.starts_with("./tmp/") {
            return Some(PolicyDecision::Deny {
                reason: format!(
                    "[{}] Execution of files in /tmp is not permitted: '{}'",
                    rule.id, command
                ),
            });
        }
        // Also check first arg if command is an interpreter
        if let Some(args) = call.param_array("args") {
            if let Some(first) = args.first().and_then(|v| v.as_str()) {
                let norm = first.replace('\\', "/");
                if norm.starts_with("/tmp/") {
                    return Some(PolicyDecision::Deny {
                        reason: format!(
                            "[{}] Execution of files in /tmp is not permitted (arg): '{}'",
                            rule.id, first
                        ),
                    });
                }
            }
        }
        None
    }

    // Rule 5: RequireConfirmation for bulk delete operations (> 3 files).
    fn rule_bulk_delete(&self, rule: &PolicyRule, call: &ToolCall) -> Option<PolicyDecision> {
        let delete_tools = ["delete_file", "remove_file", "rm", "unlink", "delete_files"];
        if !delete_tools.contains(&call.tool_name.as_str()) {
            // Also catch run_command calls to rm/del
            if call.tool_name == "run_command" {
                let cmd = call.param_str("command").unwrap_or("");
                if cmd == "rm" || cmd == "del" || cmd == "Remove-Item" {
                    if let Some(args) = call.param_array("args") {
                        // Heuristic: count non-flag arguments
                        let file_args: Vec<_> = args
                            .iter()
                            .filter_map(|v| v.as_str())
                            .filter(|s| !s.starts_with('-'))
                            .collect();
                        if file_args.len() > 3 {
                            return Some(PolicyDecision::RequireConfirmation {
                                message: format!(
                                    "[{}] 'rm'/'del' is about to delete {} files: {:?}. Approve?",
                                    rule.id,
                                    file_args.len(),
                                    file_args
                                ),
                            });
                        }
                    }
                }
            }
            return None;
        }

        // Check for a "paths" or "files" array parameter.
        for key in &["paths", "files", "targets"] {
            if let Some(arr) = call.param_array(key) {
                if arr.len() > 3 {
                    return Some(PolicyDecision::RequireConfirmation {
                        message: format!(
                            "[{}] Bulk delete of {} files requested via '{}'. \
                             Files: {:?}. Approve?",
                            rule.id,
                            arr.len(),
                            call.tool_name,
                            arr
                        ),
                    });
                }
            }
        }
        None
    }

    // -----------------------------------------------------------------------
    // Starter rules
    // -----------------------------------------------------------------------

    fn add_starter_rules(&mut self) {
        self.add_rule(PolicyRule {
            id: "path-traversal-deny".to_string(),
            description: "Deny any tool call where a path parameter contains '..' (directory traversal attack prevention).".to_string(),
            action: RuleAction::Deny,
            priority: 10,
        });

        self.add_rule(PolicyRule {
            id: "write-outside-home-deny".to_string(),
            description: "Deny write_file calls targeting paths outside the user's home directory unless an explicit grant is present in context.".to_string(),
            action: RuleAction::Deny,
            priority: 20,
        });

        self.add_rule(PolicyRule {
            id: "raw-ip-network-confirm".to_string(),
            description: "Require human confirmation when a network tool targets a raw IP address rather than a hostname — possible C2 beaconing.".to_string(),
            action: RuleAction::RequireConfirmation,
            priority: 30,
        });

        self.add_rule(PolicyRule {
            id: "tmp-exec-deny".to_string(),
            description: "Deny execution of binaries or scripts located in /tmp — common pattern for dropped malware.".to_string(),
            action: RuleAction::Deny,
            priority: 40,
        });

        self.add_rule(PolicyRule {
            id: "bulk-delete-confirm".to_string(),
            description: "Require human confirmation before deleting more than 3 files in a single tool call.".to_string(),
            action: RuleAction::RequireConfirmation,
            priority: 50,
        });
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn engine() -> PolicyEngine {
        PolicyEngine::with_default_rules()
    }

    #[test]
    fn test_path_traversal_denied() {
        let call = ToolCall::new("read_file", json!({ "path": "../../etc/passwd" }));
        let (decision, rule) = engine().evaluate(&call);
        assert!(matches!(decision, PolicyDecision::Deny { .. }));
        assert_eq!(rule.as_deref(), Some("path-traversal-deny"));
    }

    #[test]
    fn test_normal_path_allowed() {
        let call = ToolCall::new("read_file", json!({ "path": "/home/user/notes.txt" }));
        let (decision, _) = engine().evaluate(&call);
        assert_eq!(decision, PolicyDecision::Allow);
    }

    #[test]
    fn test_write_outside_home_denied() {
        let call = ToolCall::new("write_file", json!({ "path": "/etc/cron.d/evil" }));
        let (decision, rule) = engine().evaluate(&call);
        assert!(matches!(decision, PolicyDecision::Deny { .. }));
        assert_eq!(rule.as_deref(), Some("write-outside-home-deny"));
    }

    #[test]
    fn test_write_inside_home_allowed() {
        let mut call = ToolCall::new("write_file", json!({ "path": "/home/lumen/doc.txt" }));
        call.context.insert("home_dir".to_string(), "/home/lumen".to_string());
        let (decision, _) = engine().evaluate(&call);
        assert_eq!(decision, PolicyDecision::Allow);
    }

    #[test]
    fn test_raw_ip_connection_requires_confirmation() {
        let call = ToolCall::new("http_request", json!({ "url": "http://192.168.1.200/beacon" }));
        let (decision, rule) = engine().evaluate(&call);
        assert!(matches!(decision, PolicyDecision::RequireConfirmation { .. }));
        assert_eq!(rule.as_deref(), Some("raw-ip-network-confirm"));
    }

    #[test]
    fn test_tmp_exec_denied() {
        let call = ToolCall::new("run_command", json!({ "command": "/tmp/dropper.sh", "args": [] }));
        let (decision, rule) = engine().evaluate(&call);
        assert!(matches!(decision, PolicyDecision::Deny { .. }));
        assert_eq!(rule.as_deref(), Some("tmp-exec-deny"));
    }

    #[test]
    fn test_bulk_delete_requires_confirmation() {
        let call = ToolCall::new(
            "delete_files",
            json!({ "paths": ["a.txt", "b.txt", "c.txt", "d.txt"] }),
        );
        let (decision, rule) = engine().evaluate(&call);
        assert!(matches!(decision, PolicyDecision::RequireConfirmation { .. }));
        assert_eq!(rule.as_deref(), Some("bulk-delete-confirm"));
    }

    #[test]
    fn test_small_delete_allowed() {
        let call = ToolCall::new(
            "delete_files",
            json!({ "paths": ["a.txt", "b.txt"] }),
        );
        let (decision, _) = engine().evaluate(&call);
        assert_eq!(decision, PolicyDecision::Allow);
    }
}

// Helper on PolicyDecision for test ergonomics
impl PolicyDecision {
    pub fn deny_reason(&self) -> Option<String> {
        if let PolicyDecision::Deny { reason } = self {
            Some(reason.clone())
        } else {
            None
        }
    }
}
