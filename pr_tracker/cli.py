"""CLI entry point for the PR tracker."""

from __future__ import annotations

import argparse
import sys

from rich.console import Console

from .config import load_people, load_tracker_config, save_tracker_config
from .data import (
    deploy_to_runner,
    fetch_pinned,
    fetch_pr_list,
    fetch_rate_limit,
    get_runner_status,
    parse_ref,
)
from .display import console as display_console, render_issue_table, render_linear_issue_table, render_pr_table, render_rate_limit, render_slack_mention_table
from .tags import add_tag, remove_tag, list_all_tags

console = Console()


def cmd_list(args: argparse.Namespace) -> None:
    """List PRs (default command)."""
    people = load_people()
    if not people:
        console.print("[red]No people found in config/people.json[/red]")
        return

    state = "closed" if args.closed else "open"
    title = "Closed/Merged PRs" if args.closed else "Open PRs"

    console.print(f"[dim]Fetching {state} PRs...[/dim]")
    results = fetch_pr_list(
        repo=args.repo,
        state=state,
        author=args.author,
        tag=args.tag,
        stale_days=args.stale,
        fast=args.fast,
    )

    for group in results:
        if group.get("error"):
            console.print(f"[red]Error fetching {group['repo']}: {group['error']}[/red]")
            continue
        render_pr_table(group["prs"], repo=group["repo"], title=title)

    # Also show pinned items from other repos
    if not args.repo:
        pinned_groups = fetch_pinned(state=state)
        for group in pinned_groups:
            if group.get("prs"):
                render_pr_table(group["prs"], repo=group["repo"], title="Pinned PRs")
            if group.get("issues"):
                render_issue_table(group["issues"], repo=group["repo"], title="Pinned Issues")


def cmd_show(args: argparse.Namespace) -> None:
    """Show details for a specific PR or issue."""
    try:
        repo, number = parse_ref(args.ref)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return

    console.print(f"[dim]Fetching {repo}#{number}...[/dim]")
    try:
        from .data import fetch_pr_detail
        pr = fetch_pr_detail(repo, number)
        render_pr_table([pr], repo=repo, title=f"PR #{number}")
    except Exception:
        try:
            from .data import fetch_issue_detail
            issue = fetch_issue_detail(repo, number)
            render_issue_table([issue], repo=repo, title=f"Issue #{number}")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


def cmd_pin(args: argparse.Namespace) -> None:
    """Pin a PR or issue from any repo for tracking."""
    try:
        repo, number = parse_ref(args.ref)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return
    config = load_tracker_config()
    entry = {"repo": repo, "number": number, "type": args.type}
    config["pinned"] = [
        p for p in config["pinned"]
        if not (p["repo"] == repo and p["number"] == number)
    ]
    config["pinned"].append(entry)
    save_tracker_config(config)
    console.print(f"[green]Pinned {repo}#{number} ({args.type})[/green]")


def cmd_unpin(args: argparse.Namespace) -> None:
    """Unpin a PR or issue."""
    try:
        repo, number = parse_ref(args.ref)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return
    config = load_tracker_config()
    config["pinned"] = [
        p for p in config["pinned"]
        if not (p["repo"] == repo and p["number"] == number)
    ]
    save_tracker_config(config)
    console.print(f"[yellow]Unpinned {repo}#{number}[/yellow]")


def cmd_tag(args: argparse.Namespace) -> None:
    """Add or remove a custom tag."""
    if args.action == "add":
        add_tag(args.ref, args.tag)
        console.print(f"[green]Tagged {args.ref} with '{args.tag}'[/green]")
    elif args.action == "rm":
        remove_tag(args.ref, args.tag)
        console.print(f"[yellow]Removed '{args.tag}' from {args.ref}[/yellow]")
    elif args.action == "list":
        tags = list_all_tags()
        if not tags:
            console.print("[dim]No tags set[/dim]")
        for key, vals in tags.items():
            console.print(f"  {key}: {', '.join(vals)}")


def cmd_deploy(args: argparse.Namespace) -> None:
    """Deploy a PR/branch to a running comfy-runner server instance."""
    from .config import load_runner_servers
    server_url = args.server
    if not server_url:
        servers = load_runner_servers()
        server_url = servers[0]["url"] if servers else "http://127.0.0.1:9189"

    if args.status:
        data = get_runner_status(server_url)
        if data.get("ok"):
            running = "running" if data.get("running") else "stopped"
            port = data.get("port", "?")
            pid = data.get("pid", "?")
            head = data.get("head_commit", "?")[:8] if data.get("head_commit") else "?"
            tunnel = data.get("tunnel_url", "")
            console.print(f"[bold]Status:[/bold] {running}")
            console.print(f"[bold]Port:[/bold] {port}  [bold]PID:[/bold] {pid}")
            console.print(f"[bold]HEAD:[/bold] {head}")
            if data.get("uptime"):
                console.print(f"[bold]Uptime:[/bold] {data['uptime']}")
            if tunnel:
                console.print(f"[bold]Tunnel:[/bold] {tunnel}")
        else:
            console.print(f"[red]Error: {data.get('error', 'Unknown error')}[/red]")
        return

    # Deploy a PR, branch, tag, commit, or reset
    body: dict = {}
    if args.ref:
        try:
            repo, number = parse_ref(args.ref)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return
        body["pr"] = number
    elif args.branch:
        body["branch"] = args.branch
    elif args.tag:
        body["tag"] = args.tag
    elif args.commit:
        body["commit"] = args.commit
    elif args.reset:
        body["reset"] = True
    else:
        console.print("[red]Specify a PR ref (e.g. ComfyUI#12812), --branch, --tag, --commit, or --reset[/red]")
        return

    console.print(f"[dim]Deploying to {server_url}...[/dim]")
    data = deploy_to_runner(body, server_url)
    if data.get("ok"):
        console.print("[green]Deploy succeeded[/green]")
        if data.get("new_head"):
            console.print(f"  HEAD: {data['new_head'][:8]}")
        if data.get("requirements_installed"):
            console.print("  Requirements reinstalled")
        if data.get("restarted"):
            console.print(f"  Restarted on port {data.get('port', '?')}")
        for line in data.get("output", []):
            console.print(f"  [dim]{line}[/dim]")
    else:
        console.print(f"[red]Deploy failed: {data.get('error', 'Unknown error')}[/red]")


def cmd_rate(args: argparse.Namespace) -> None:
    """Show GitHub API rate limit."""
    info = fetch_rate_limit()
    render_rate_limit(info)


# ---------------------------------------------------------------------------
# Linear commands
# ---------------------------------------------------------------------------

def cmd_linear(args: argparse.Namespace) -> None:
    """Route Linear subcommands."""
    action = getattr(args, "linear_action", None)
    if not action:
        console.print("[red]Usage: pr_tracker linear {list|show|teams}[/red]")
        return
    action(args)


def cmd_linear_list(args: argparse.Namespace) -> None:
    """List Linear issues for configured teams."""
    from .config import load_linear_config
    from .linear_data import fetch_linear_issues, fetch_my_linear_issues

    config = load_linear_config()
    if not config.get("linear_teams"):
        console.print("[red]No linear_teams configured in pr-tracker.json[/red]")
        return

    # Map state filter names to Linear state types
    state_map = {
        "todo": ["unstarted"],
        "in-progress": ["started"],
        "done": ["completed"],
        "backlog": ["backlog"],
        "cancelled": ["cancelled"],
        "active": ["unstarted", "started"],
        "all": None,
    }
    states = state_map.get(args.state, ["unstarted", "started", "backlog"]) if args.state else None

    team_names = [args.team] if args.team else None

    console.print("[dim]Fetching Linear issues...[/dim]")
    if args.mine:
        issues = fetch_my_linear_issues(states=states, first=50)
    else:
        issues = fetch_linear_issues(team_names=team_names, states=states, first=50)

    if team_names:
        title = f"Linear Issues — {args.team}"
    elif args.mine:
        title = "My Linear Issues"
    else:
        title = "Linear Issues — " + ", ".join(config["linear_teams"])

    render_linear_issue_table(issues, title=title)


def cmd_linear_show(args: argparse.Namespace) -> None:
    """Show details for a specific Linear issue."""
    from .linear_data import fetch_linear_issue_detail

    identifier = args.identifier
    console.print(f"[dim]Fetching {identifier}...[/dim]")
    detail = fetch_linear_issue_detail(identifier)
    if not detail:
        console.print(f"[red]Issue {identifier} not found[/red]")
        return

    render_linear_issue_table([detail], title=f"Linear Issue — {identifier}")

    # Show description
    body = detail.get("body", "")
    if body:
        console.print("[bold]Description:[/bold]")
        console.print(body[:500])
        if len(body) > 500:
            console.print("[dim]... (truncated)[/dim]")
        console.print()

    # Show comments
    comments = detail.get("comments", [])
    if comments:
        console.print(f"[bold]Comments ({len(comments)}):[/bold]")
        for c in comments:
            console.print(f"  [blue]{c['author']}[/blue] ({c['created_ago']}): {c['body'][:120]}")
        console.print()

    # Show URL
    url = detail.get("url", "")
    if url:
        console.print(f"[bold]URL:[/bold] {url}")


def cmd_linear_teams(args: argparse.Namespace) -> None:
    """List available Linear teams."""
    from .linear_api import fetch_teams

    console.print("[dim]Fetching teams...[/dim]")
    teams = fetch_teams()
    if not teams:
        console.print("[red]No teams found (check lineartoken.txt)[/red]")
        return
    console.print("[bold]Available Linear teams:[/bold]")
    for t in teams:
        console.print(f"  [bold]{t['key']:8s}[/bold] {t['name']}")


# ---------------------------------------------------------------------------
# Slack commands
# ---------------------------------------------------------------------------

def cmd_slack(args: argparse.Namespace) -> None:
    """Route Slack subcommands."""
    action = getattr(args, "slack_action", None)
    if not action:
        console.print("[red]Usage: pr_tracker slack {mentions|search}[/red]")
        return
    action(args)


def cmd_slack_mentions(args: argparse.Namespace) -> None:
    """List recent Slack mentions."""
    from .config import load_slack_config
    from .slack_data import fetch_mentions

    config = load_slack_config()
    if not config.get("slack_user_id"):
        console.print("[red]No slack_user_id configured in pr-tracker.json[/red]")
        return

    hours = args.hours or 24
    console.print(f"[dim]Fetching Slack mentions (last {hours}h)...[/dim]")
    mentions = fetch_mentions(since_hours=hours, actions_only=args.actions)

    title = "Actionable Mentions" if args.actions else f"Mentions (last {hours}h)"
    render_slack_mention_table(mentions, title=title)


def cmd_slack_search(args: argparse.Namespace) -> None:
    """Search Slack messages."""
    from .slack_data import search_slack

    query = args.query
    console.print(f"[dim]Searching Slack for '{query}'...[/dim]")
    results = search_slack(query, count=args.count)
    render_slack_mention_table(results, title=f"Search: {query}")


def cmd_repo(args: argparse.Namespace) -> None:
    """Add or remove a repo from the tracked list."""
    config = load_tracker_config()
    if args.action == "add":
        if args.name not in config["repos"]:
            config["repos"].append(args.name)
            save_tracker_config(config)
            console.print(f"[green]Added {args.name} to tracked repos[/green]")
        else:
            console.print(f"[dim]{args.name} already tracked[/dim]")
    elif args.action == "rm":
        if args.name in config["repos"]:
            config["repos"].remove(args.name)
            save_tracker_config(config)
            console.print(f"[yellow]Removed {args.name} from tracked repos[/yellow]")
        else:
            console.print(f"[dim]{args.name} not in tracked repos[/dim]")
    elif args.action == "list":
        for r in config["repos"]:
            console.print(f"  {r}")


def _resolve_runpod_url(pod_name: str) -> tuple[str, str]:
    """Look up a RunPod pod by name and return (name, proxy_url).

    Reads the pod registry from comfy-runner's config to find the pod ID,
    then constructs the RunPod proxy URL for port 9189.

    Raises ``RuntimeError`` if the pod is not found.
    """
    from comfy_runner.hosted.config import get_provider_config

    pods = get_provider_config("runpod").get("pods", {})
    record = pods.get(pod_name)
    if not record:
        available = ", ".join(pods.keys()) if pods else "(none)"
        raise RuntimeError(
            f"Pod '{pod_name}' not found in comfy-runner config. "
            f"Available: {available}"
        )
    pod_id = record.get("id", "")
    if not pod_id:
        raise RuntimeError(f"Pod '{pod_name}' has no ID in config")
    url = f"https://{pod_id}-9189.proxy.runpod.net"
    return pod_name, url


def cmd_server(args: argparse.Namespace) -> None:
    """Manage runner server entries in pr-tracker config."""
    from .config import load_runner_servers, save_runner_servers

    action = args.action

    if action == "list":
        servers = load_runner_servers()
        if not servers:
            console.print("[dim]No runner servers configured[/dim]")
            return
        for s in servers:
            console.print(f"  [bold]{s['name']}[/bold]  {s['url']}")

    elif action == "add":
        runpod = getattr(args, "runpod", None)
        raw = args.entry

        if runpod:
            # Resolve RunPod pod name → proxy URL
            try:
                name, url = _resolve_runpod_url(runpod)
            except RuntimeError as e:
                console.print(f"[red]{e}[/red]")
                return
        elif raw:
            if "=" in raw and not raw.startswith(("http://", "https://")):
                name, url = raw.split("=", 1)
                name = name.strip()
                url = url.strip()
            else:
                url = raw
                name = ""
            if not url.startswith(("http://", "https://")):
                console.print("[red]URL must start with http:// or https://[/red]")
                return
        else:
            console.print("[red]Usage: server add name=https://host:port  or  server add --runpod <pod_name>[/red]")
            return

        servers = load_runner_servers()
        if not name:
            i = 1
            existing = {s["name"] for s in servers}
            while f"server-{i}" in existing:
                i += 1
            name = f"server-{i}"
        # Update if name exists
        for s in servers:
            if s["name"] == name:
                s["url"] = url
                save_runner_servers(servers)
                console.print(f"[yellow]Updated {name} -> {url}[/yellow]")
                return
        servers.append({"name": name, "url": url})
        save_runner_servers(servers)
        console.print(f"[green]Added server '{name}' at {url}[/green]")

    elif action == "rm":
        name = args.entry
        if not name:
            console.print("[red]Usage: pr_tracker server rm <name>[/red]")
            return
        servers = load_runner_servers()
        new = [s for s in servers if s["name"] != name]
        if len(new) == len(servers):
            console.print(f"[dim]Server '{name}' not found[/dim]")
            return
        save_runner_servers(new)
        console.print(f"[yellow]Removed server '{name}'[/yellow]")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pr-tracker",
        description="Track PRs and issues across ComfyUI repos",
    )
    sub = parser.add_subparsers(dest="command")

    # Default: list PRs
    p_list = sub.add_parser("list", aliases=["ls"], help="List PRs by tracked people")
    p_list.add_argument("--repo", "-r", help="Filter to a specific repo (owner/repo)")
    p_list.add_argument("--author", "-a", help="Filter to a specific author")
    p_list.add_argument("--tag", "-t", help="Filter by custom tag")
    p_list.add_argument("--stale", type=int, metavar="DAYS", help="Only show PRs with no activity in N+ days")
    p_list.add_argument("--closed", action="store_true", help="Show closed/merged PRs instead of open")
    p_list.add_argument("--fast", "-f", action="store_true", help="Skip CI and behind-base checks (faster)")
    p_list.set_defaults(func=cmd_list)

    # Show a specific PR/issue
    p_show = sub.add_parser("show", help="Show details for a PR or issue")
    p_show.add_argument("ref", help="PR/issue reference (e.g. ComfyUI#1234)")
    p_show.set_defaults(func=cmd_show)

    # Pin/unpin one-off items from any repo
    p_pin = sub.add_parser("pin", help="Pin a PR/issue from any repo")
    p_pin.add_argument("ref", help="Reference (e.g. owner/repo#123)")
    p_pin.add_argument("--type", choices=["pr", "issue"], default="pr")
    p_pin.set_defaults(func=cmd_pin)

    p_unpin = sub.add_parser("unpin", help="Unpin a PR/issue")
    p_unpin.add_argument("ref", help="Reference (e.g. owner/repo#123)")
    p_unpin.set_defaults(func=cmd_unpin)

    # Tag management
    p_tag = sub.add_parser("tag", help="Manage custom tags on PRs/issues")
    p_tag.add_argument("action", choices=["add", "rm", "list"])
    p_tag.add_argument("ref", nargs="?", help="PR/issue reference")
    p_tag.add_argument("tag", nargs="?", help="Tag name")
    p_tag.set_defaults(func=cmd_tag)

    # Repo management
    p_repo = sub.add_parser("repo", help="Manage tracked repos")
    p_repo.add_argument("action", choices=["add", "rm", "list"])
    p_repo.add_argument("name", nargs="?", help="Repo in owner/repo format")
    p_repo.set_defaults(func=cmd_repo)

    # Server management
    p_server = sub.add_parser("server", help="Manage runner server entries")
    p_server.add_argument("action", choices=["add", "rm", "list"])
    p_server.add_argument("entry", nargs="?", help="name=url (add) or name (rm)")
    p_server.add_argument("--runpod", metavar="POD", help="Add a RunPod pod by name (resolves proxy URL from comfy-runner config)")
    p_server.set_defaults(func=cmd_server)

    # Deploy to comfy-runner server
    p_deploy = sub.add_parser("deploy", help="Deploy a PR/branch to comfy-runner server")
    p_deploy.add_argument("ref", nargs="?", help="PR reference (e.g. ComfyUI#12812)")
    p_deploy.add_argument("--branch", help="Deploy a branch")
    p_deploy.add_argument("--tag", help="Deploy a tag")
    p_deploy.add_argument("--commit", help="Deploy a specific commit")
    p_deploy.add_argument("--reset", action="store_true", help="Reset to original release ref")
    p_deploy.add_argument("--status", action="store_true", help="Show runner status instead of deploying")
    p_deploy.add_argument("--server", help="Runner server URL (default: from config or http://127.0.0.1:9189)")
    p_deploy.set_defaults(func=cmd_deploy)

    # Linear
    p_linear = sub.add_parser("linear", help="Linear issue tracking")
    p_linear.set_defaults(func=cmd_linear)
    linear_sub = p_linear.add_subparsers(dest="linear_cmd")

    p_linear_list = linear_sub.add_parser("list", aliases=["ls"], help="List Linear issues")
    p_linear_list.add_argument("--team", "-t", help="Filter to a specific team name or key")
    p_linear_list.add_argument("--state", "-s", choices=["todo", "in-progress", "done", "backlog", "active", "all"],
                               help="Filter by state")
    p_linear_list.add_argument("--mine", "-m", action="store_true", help="Only show issues assigned to me")
    p_linear_list.set_defaults(linear_action=cmd_linear_list)

    p_linear_show = linear_sub.add_parser("show", help="Show Linear issue detail")
    p_linear_show.add_argument("identifier", help="Issue identifier (e.g. CORE-123)")
    p_linear_show.set_defaults(linear_action=cmd_linear_show)

    p_linear_teams = linear_sub.add_parser("teams", help="List available Linear teams")
    p_linear_teams.set_defaults(linear_action=cmd_linear_teams)

    # Slack
    p_slack = sub.add_parser("slack", help="Slack mention tracking")
    p_slack.set_defaults(func=cmd_slack)
    slack_sub = p_slack.add_subparsers(dest="slack_cmd")

    p_slack_mentions = slack_sub.add_parser("mentions", aliases=["m"], help="List recent @mentions")
    p_slack_mentions.add_argument("--hours", "-H", type=int, default=24, help="Look back N hours (default: 24)")
    p_slack_mentions.add_argument("--actions", "-a", action="store_true", help="Only show actionable mentions")
    p_slack_mentions.set_defaults(slack_action=cmd_slack_mentions)

    p_slack_search = slack_sub.add_parser("search", aliases=["s"], help="Search Slack messages")
    p_slack_search.add_argument("query", help="Search query")
    p_slack_search.add_argument("--count", "-c", type=int, default=20, help="Number of results")
    p_slack_search.set_defaults(slack_action=cmd_slack_search)

    # Rate limit
    p_rate = sub.add_parser("rate", help="Show GitHub API rate limit")
    p_rate.set_defaults(func=cmd_rate)

    # If no subcommand given (or first arg looks like a flag), default to 'list'
    effective_argv = argv if argv is not None else sys.argv[1:]
    if not effective_argv or effective_argv[0].startswith("-"):
        effective_argv = ["list"] + list(effective_argv)

    args = parser.parse_args(effective_argv)
    args.func(args)


if __name__ == "__main__":
    main()
