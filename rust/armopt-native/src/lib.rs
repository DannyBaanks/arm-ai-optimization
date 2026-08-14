//! armopt-native - Native Rust engine for Arm AI Optimization Harness
//! 
//! Same contract as Python reference implementation:
//! - JSONL protocol: {"prompt": "...", "max_tokens": 64} -> {"text": "...", "input_tokens": 4, "output_tokens": 12}
//! - Modes: sequential (w=1) and dataflow (w=N pool)
//! - Evidence: SHA256-signed JSON matching Python evidence schema

pub mod contract;
pub mod engine;
pub mod metrics;

/// Engine version
pub const VERSION: &str = env!("CARGO_PKG_VERSION");