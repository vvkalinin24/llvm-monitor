#!/usr/bin/env python3
"""
LLVM Monitor - Multi-Agent System

Main entry point for running the LLVM monitoring system.
Uses multiple specialized agents coordinated by an orchestrator.
"""

import argparse
import logging
import yaml
import time
from pathlib import Path
from datetime import datetime

from agents import Orchestrator


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if path.exists():
        return yaml.safe_load(path.read_text())
    return {}


def run_once(orchestrator: Orchestrator, args) -> dict:
    """Run a single monitoring cycle."""
    output_path = None
    if not args.no_save:
        output_dir = Path(orchestrator.get_config('notifications.file.output_dir', 'reports'))
        output_dir.mkdir(exist_ok=True)
        ext = {'markdown': 'md', 'json': 'json', 'text': 'txt'}.get(args.format, 'md')
        output_path = str(output_dir / f"report_{datetime.now().strftime('%Y-%m-%d_%H%M')}.{ext}")

    result = orchestrator.run({
        'include_seen': args.all,
        'format': args.format,
        'output_path': output_path
    })

    return result


def run_daemon(orchestrator: Orchestrator, interval_minutes: int, args):
    """Run in daemon mode with periodic checks."""
    print(f"LLVM Monitor daemon started (interval: {interval_minutes} min)")
    print("Press Ctrl+C to stop\n")

    while True:
        try:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Running check...")
            result = run_once(orchestrator, args)

            if result['status'] == 'success':
                summary = result['summary']
                print(f"Found {summary['total']} updates "
                      f"({summary['high']} high, {summary['medium']} medium, {summary['low']} low)")
                if result.get('output_path'):
                    print(f"Report saved: {result['output_path']}")
            else:
                print(f"Error: {result.get('error', 'Unknown error')}")

            print()

        except KeyboardInterrupt:
            print("\nStopping daemon...")
            break
        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(interval_minutes * 60)


def main():
    parser = argparse.ArgumentParser(
        description='LLVM Monitor - Multi-Agent System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Run once, save report
  %(prog)s --all              # Include already seen items
  %(prog)s --format json      # Output as JSON
  %(prog)s --daemon           # Run continuously
  %(prog)s --agent github     # Run only GitHub agent
  %(prog)s --agent analyzer   # Run analyzer on previous results
"""
    )

    parser.add_argument('--config', '-c', default='config.yaml',
                       help='Path to configuration file')
    parser.add_argument('--format', '-f', choices=['markdown', 'text', 'json'],
                       default='markdown', help='Output format')
    parser.add_argument('--output', '-o', help='Custom output path')
    parser.add_argument('--all', '-a', action='store_true',
                       help='Include already seen items')
    parser.add_argument('--no-save', action='store_true',
                       help='Do not save report to file')
    parser.add_argument('--daemon', '-d', action='store_true',
                       help='Run in daemon mode')
    parser.add_argument('--agent', help='Run specific agent (github, discourse, blog, analyzer, reporter)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose logging')

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Load config
    script_dir = Path(__file__).parent
    config_path = script_dir / args.config
    if not config_path.exists():
        config_path = Path(args.config)

    config = load_config(str(config_path))

    # Create orchestrator
    orchestrator = Orchestrator(config)

    # Run specific agent if requested
    if args.agent:
        print(f"Running agent: {args.agent}")
        result = orchestrator.call_agent(args.agent)
        if result['status'] == 'success':
            print(f"Success: {result.get('count', 0)} items")
            if args.verbose:
                import json
                print(json.dumps(result, indent=2))
        else:
            print(f"Error: {result.get('error')}")
        return

    # Daemon mode
    if args.daemon:
        interval = config.get('schedule', {}).get('interval_minutes', 60)
        run_daemon(orchestrator, interval, args)
        return

    # Single run
    print("Starting LLVM Monitor (Multi-Agent System)")
    print("=" * 50)

    result = run_once(orchestrator, args)

    if result['status'] == 'success':
        # Print report
        print("\n" + result['report'])

        if result.get('output_path'):
            print(f"\nReport saved: {result['output_path']}")
    else:
        print(f"Error: {result.get('error', 'Unknown error')}")


if __name__ == '__main__':
    main()
