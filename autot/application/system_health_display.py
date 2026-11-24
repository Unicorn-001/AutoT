"""Lightweight operational workspace; no worker launch or recovery actions."""
import streamlit as st

from autot.application.system_health import snapshot, HEARTBEAT_GRACE_SECONDS


@st.fragment(run_every='15s')
def render_system_health():
    status = snapshot()
    st.subheader('System Health / Status')
    st.caption(f"Observed: {status['checked_at']} · Refreshes every 15 seconds")
    st.button('Refresh health status')
    if status['settings_warning']:
        st.warning('Monitoring configuration is unverified: ' + status['settings_warning'])
    for column, key, title in zip(st.columns(2), ('scanner', 'paper'), ('Scanner', 'Paper monitor')):
        service = status[key]
        with column:
            st.metric(title, service['health'])
            st.write(service['reason'])
            configured = {True: 'ON', False: 'OFF', None: 'UNKNOWN'}[service['configured']]
            st.caption(f"Configured: {configured} · Process: {service['process_status']}")
            if key == 'scanner' and not service.get('unavailable'):
                st.caption(f"Scheduler lock: {service['scheduler_active']} · Worker lock: {service['worker_active']}")
            st.text('Phase: ' + str(service.get('phase') or 'Not recorded'))
            st.text('Heartbeat: ' + str(service.get('heartbeat') or 'Not recorded'))
            st.text('Next expected run: ' + str(service.get('next_expected_run') or 'Not recorded'))
            run = service.get('last_run')
            if run:
                st.text('Last run: ' + str(run.get('completed_at') or run.get('started_at') or run.get('requested_at') or 'Not recorded'))
                st.text(('Last scanner result status: ' if key == 'scanner' else 'Last scheduled update status: ') + str(run.get('status', 'Unknown')))
            else:
                st.text('Run history unavailable' if service.get('unavailable') else 'No prior runs recorded')
    paper = status['paper']
    for column, key, label in zip(st.columns(2), ('pending', 'open'), ('Pending paper trades', 'Open paper trades')):
        column.metric(label, paper.get(key) if paper.get(key) is not None else 'Unavailable')
    st.write('Recent warnings / errors')
    issues = []
    for run in status['scanner'].get('recent_issues', []):
        issues.append(f"Scanner · {run.get('completed_at') or run.get('requested_at')} · {run['status']} · {run.get('error_category') or 'Partial results'}")
    failure = paper.get('last_failure')
    if failure:
        issues.append(f"Paper monitor · {failure.get('completed_at') or failure.get('started_at')} · {failure.get('status')} · warnings: {failure.get('warnings_count', 0)}, errors: {failure.get('errors_count', 0)}")
    latest = paper.get('last_run') or {}
    if latest != failure and (latest.get('warnings_count') or latest.get('errors_count')):
        issues.append(f"Latest paper update · warnings: {latest.get('warnings_count', 0)}, errors: {latest.get('errors_count', 0)}")
    for issue in issues:
        st.warning(issue)
    if not issues:
        st.caption('No warnings/errors found in available history.' if not any(status[k].get('unavailable') for k in ('scanner', 'paper')) else 'Some history is unavailable.')
    config = status['monitoring']
    st.write('Monitoring configuration' + (' (fallback; unverified)' if status['settings_warning'] else ''))
    st.text(f'Paper update interval: {config.paper_update_interval_minutes} minutes')
    st.text(f'Daily scan time: {config.daily_scan_time_local} market-local (subject to session close/publication buffer)')
    st.caption(f'Waiting services allow {HEARTBEAT_GRACE_SECONDS} seconds for heartbeat/deadline delays. Paper updates use their configured cadence plus this grace. Active scans have progress-driven heartbeats and no recorded completion deadline: RUNNING means a held worker lock with unverified progress. Process detection is local to this host. Scanner issues cover the latest 20 runs; paper issues show the latest failed/partial scheduled update.')
    st.write('Runtime data directory')
    st.code(status['data_directory'], language=None)

    st.write('Startup / recovery diagnostics')
    st.json(status['recovery'])

    st.write('Data backups')
    st.json(status['backup'])
    if status['backup']['warning']:
        st.warning(status['backup']['warning'])
