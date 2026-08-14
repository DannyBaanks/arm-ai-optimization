//! CLI - Matches Python armopt.cli interface
use anyhow::Result;
use clap::{Parser, Subcommand};
use std::path::PathBuf;

use armopt_native::contract::{BenchmarkConfig, EngineMode, EvidenceRecord};
use armopt_native::engine::DemoEngine;
use armopt_native::metrics::{generate_evidence, verify_evidence, write_evidence};

#[derive(Parser)]
#[command(name = "armopt-native", version, about = "Native Rust engine for Arm AI Optimization Harness")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Run benchmark (sequential, dataflow, or both)
    Benchmark {
        /// Number of requests
        #[arg(long, default_value = "100")]
        requests: usize,
        
        /// Number of workers (dataflow mode)
        #[arg(long, default_value = "4")]
        workers: usize,
        
        /// Number of repeats (median taken)
        #[arg(long, default_value = "3")]
        repeats: usize,
        
        /// Mode: sequential, dataflow, or both
        #[arg(long, default_value = "both")]
        mode: String,
        
        /// Output evidence file
        #[arg(long)]
        evidence: Option<PathBuf>,
        
        /// Workload ID
        #[arg(long, default_value = "inline-demo")]
        workload_id: String,
    },
    
    /// Verify evidence file
    Verify {
        /// Evidence file to verify
        evidence: PathBuf,
    },
    
    /// Run full pipeline (benchmark + verify)
    Pipeline {
        #[arg(long, default_value = "100")]
        requests: usize,
        #[arg(long, default_value = "4")]
        workers: usize,
        #[arg(long, default_value = "3")]
        repeats: usize,
        #[arg(long, default_value = "inline-demo")]
        workload_id: String,
    },
}

#[cfg(not(target_arch = "wasm32"))]
#[tokio::main]
async fn main() -> Result<()> {
    run_main().await
}

#[cfg(target_arch = "wasm32")]
fn main() {
    // WASM: run with futures executor
    futures::executor::block_on(run_main()).unwrap();
}

async fn run_main() -> Result<()> {
    let cli = Cli::parse();
    let engine = DemoEngine::new();
    
    match cli.command {
        Commands::Benchmark { requests, workers, repeats, mode, evidence, workload_id } => {
            let mode = match mode.to_lowercase().as_str() {
                "sequential" => EngineMode::Sequential,
                "dataflow" => EngineMode::Dataflow,
                "both" => EngineMode::Both,
                _ => anyhow::bail!("Invalid mode: {}. Use sequential, dataflow, or both", mode),
            };
            
            let engine = DemoEngine::new();
            
            if mode == EngineMode::Both {
                let mut record = EvidenceRecord::new("demo-adapter".to_string(), "inline-demo".to_string());
                
                let baseline_config = armopt_native::contract::BenchmarkConfig {
                    requests,
                    workers: 1,
                    repeats,
                    mode: EngineMode::Sequential,
                };
                let baseline = armopt_native::metrics::run_benchmark_with_repeats(&DemoEngine::new(), &baseline_config, 3).await?;
                
                let dataflow_config = armopt_native::contract::BenchmarkConfig {
                    requests,
                    workers,
                    repeats,
                    mode: EngineMode::Dataflow,
                };
                let dataflow = armopt_native::metrics::run_benchmark_with_repeats(&DemoEngine::new(), &dataflow_config, 3).await?;
                
                println!("{}", serde_json::to_string(&baseline)?);
                println!("{}", serde_json::to_string(&dataflow)?);
                
                if let Some(ref path) = evidence {
                    let mut record = EvidenceRecord::new("demo-adapter".to_string(), "inline-demo".to_string());
                    record.results.baseline = Some(baseline);
                    record.results.dataflow = Some(dataflow);
                    record.results.repeats = 3;
                    if let (Some(b), Some(d)) = (&record.results.baseline, &record.results.dataflow) {
                        record.results.speedup_wall = Some(b.wall_ms as f64 / d.wall_ms as f64);
                    }
                    record.results.repeats = 3;
                    write_evidence(&mut record, path.as_path())?;
                    eprintln!("evidence written to {}", path.display());
                }
            } else {
                let config = armopt_native::contract::BenchmarkConfig {
                    requests,
                    workers: if mode == EngineMode::Sequential { 1 } else { workers },
                    repeats: 1,
                    mode,
                };
                let result = armopt_native::metrics::run_benchmark_with_repeats(&engine, &config, 1).await?;
                println!("{}", serde_json::to_string(&result)?);
            }
        }
        
        Commands::Verify { evidence } => {
            let valid = verify_evidence(&evidence)?;
            println!("Evidence {}: {}", if valid { "VALID" } else { "INVALID" }, evidence.display());
        }
        
        Commands::Pipeline { requests, workers, repeats, workload_id } => {
            eprintln!("Running full pipeline...");
            let engine = DemoEngine::new();
            let mut record = generate_evidence(&engine, requests, workers, repeats, &workload_id).await?;
            
            let evidence_path = format!("evidence/{}_pipeline.json", workload_id);
            write_evidence(&mut record, &PathBuf::from(&evidence_path))?;
            
            let valid = verify_evidence(&PathBuf::from(&evidence_path))?;
            
            let speedup = record.results.speedup_wall.unwrap_or(0.0);
            println!("Pipeline complete. Speedup: {:.2}x", speedup);
            println!("Evidence: {} ({})", evidence_path, if valid { "VALID" } else { "INVALID" });
        }
    }
    
    Ok(())
}