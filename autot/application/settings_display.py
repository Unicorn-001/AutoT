"""Draft-only settings UI. Only explicit saves/activations reach durable storage."""
from typing import get_args, get_origin, Literal

import streamlit as st
from pydantic import BaseModel, ValidationError

from autot.universe.index_definitions import INDICES, indices_for_country, normalize_country_index_selection
from autot.settings.models import AutoTSettings
from autot.settings.store import SettingsStore
from autot.strategies.registry.strategy_registry import REGISTRY

PARAMETER_WARNING = ('Changing strategy parameters creates a new strategy configuration and '
                     'makes performance results non-comparable with previous configurations.')


def draft_model(baseline, values):
    """Retain unsaved (possibly invalid) inputs until explicit Save validates them."""
    return baseline.model_copy(update={
        name: draft_model(getattr(baseline, name), value) if isinstance(getattr(baseline, name), BaseModel) else value
        for name, value in values.items()
    })


def edit_model(model, prefix):
    values = {}
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        key = prefix + '.' + name
        label = name.replace('_', ' ').capitalize()
        annotation = field.annotation
        if isinstance(value, BaseModel):
            st.caption(label)
            values[name] = edit_model(value, key)
        elif get_origin(annotation) is Literal:
            choices = list(get_args(annotation))
            values[name] = st.selectbox(label, choices, index=choices.index(value), key=key)
        elif isinstance(value, bool):
            values[name] = st.checkbox(label, value=value, key=key)
        elif name == 'weight':
            override = st.checkbox('Override regime weights', value=value is not None, key=key+'.override')
            weight = st.number_input('Weight override', value=float(value if value is not None else 1), min_value=0.0, key=key)
            values[name] = weight if override else None
        elif name == 'top_trade_opportunity_count':
            limited = st.checkbox('Limit displayed trade opportunities', value=value is not None, key=key+'.limit')
            count = st.number_input(label, value=value or 10, min_value=1, step=1, key=key)
            values[name] = count if limited else None
        elif isinstance(value, (int, float)):
            values[name] = st.number_input(label, value=value, step=1 if isinstance(value, int) else 0.1, key=key)
        elif name == 'index':
            choices = [item.index_id for item in indices_for_country(values['country'])]
            selected = normalize_country_index_selection(values['country'], st.session_state.get(key, value))
            if key in st.session_state and st.session_state[key] != selected:
                st.session_state[key] = selected
            values[name] = st.selectbox('Default index (must match country)', choices,
                                       index=choices.index(selected), key=key,
                                       format_func=lambda item: INDICES[item].index_name)
        else:
            values[name] = st.text_input(label, value=value, key=key)
    return values


def render_settings():
    st.header('Settings')
    store = SettingsStore()
    state = store.load()
    if store.warning:
        st.warning(store.warning)
    p = state.profile
    st.subheader(f'Active: {p.profile_name} v{p.profile_version}')
    st.caption(f'{state.settings.general.mode} · Settings revision {state.settings_version} · Configuration {p.configuration_hash}')
    risk = state.settings.risk
    st.write(f'Risk/trade: {risk.risk_per_trade_percent:g}% · Maximum position: {risk.maximum_position_percent:g}% '
             f'({"enabled" if risk.enforce_position_limit else "not enforced"}) · '
             f'Maximum positions: {risk.maximum_simultaneous_positions} '
             f'({"enabled" if risk.enforce_positions_limit else "not enforced"})')
    st.dataframe([
        {'Limit': label, 'Configured': value, 'Status': 'ENFORCED' if enabled else 'INACTIVE'}
        for label, value, enabled in [
            ('Risk/trade', f'{risk.risk_per_trade_percent:g}%', True),
            ('Max position', f'{risk.maximum_position_percent:g}%', risk.enforce_position_limit),
            ('Max positions', str(risk.maximum_simultaneous_positions), risk.enforce_positions_limit),
            ('Portfolio risk', f'{risk.maximum_total_portfolio_risk_percent:g}%', risk.enforce_portfolio_risk_limit),
            ('Daily trade limit', str(risk.maximum_new_trades_per_day), risk.enforce_daily_trade_limit),
            ('Minimum R:R', f'{risk.minimum_risk_reward:g}', risk.minimum_risk_reward > 0),
            ('Allow BUY', str(risk.allow_buy), True), ('Allow SELL', str(risk.allow_sell), True),
        ]], hide_index=True)
    st.caption('Settings apply after Save. Existing scan results retain their original profile; run a new scan after saving. New limits are opt-in.')
    if 'settings_notice' in st.session_state:
        st.success(st.session_state.pop('settings_notice'))

    profiles = store.profiles()
    selected = st.selectbox('Saved profile version', range(len(profiles)),
                           format_func=lambda i: f'{profiles[i].profile_name} v{profiles[i].profile_version} · {profiles[i].profile_id}')
    if st.button('Activate profile'):
        target = profiles[selected]
        try:
            store.activate(target.profile_id, target.profile_version, expected_version=state.settings_version,
                           reason='Profile activated in Settings')
            st.session_state.pop('settings_draft', None)
            st.session_state['settings_notice'] = 'Profile activated. Run a new scan to use it.'
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))

    identity = (state.settings_version, p.profile_id, p.profile_version)
    stale_draft = st.session_state.get('settings_draft_identity') not in (None, identity)
    if st.session_state.get('settings_draft_identity') != identity or 'settings_draft' not in st.session_state:
        st.session_state['settings_draft'] = state.settings.model_dump()
        st.session_state['settings_draft_identity'] = identity
        st.session_state['settings_epoch'] = st.session_state.get('settings_epoch', 0) + 1
    draft = draft_model(AutoTSettings(), st.session_state['settings_draft'])
    section = st.selectbox('Section to reset', [k for k in AutoTSettings.model_fields if k not in ('schema_version', 'advanced')])
    if st.button('Reset Section'):
        st.session_state['settings_draft'][section] = getattr(AutoTSettings(), section).model_dump()
        st.session_state['settings_epoch'] += 1
        st.rerun()
    if st.button('Restore All Defaults'):
        st.session_state['settings_restore_pending'] = True
    if st.session_state.get('settings_restore_pending'):
        st.warning('This will reset all unsaved Settings fields to AutoT baseline defaults. '
                   'Historical trades and saved profiles will not be changed.')
        if st.button('Confirm Restore All Defaults'):
            st.session_state['settings_draft'] = AutoTSettings().model_dump()
            st.session_state['settings_epoch'] += 1
            st.session_state.pop('settings_restore_pending', None)
            st.rerun()
        if st.button('Cancel'):
            st.session_state.pop('settings_restore_pending', None)
            st.rerun()
    st.caption('Reset and restore only change this draft. Save Settings to activate it. The baseline profile remains protected.')
    prefix = f"settings_editor.{st.session_state['settings_epoch']}"
    with st.container():
        new_profile = st.checkbox('Create / duplicate as a NEW profile', value=p.builtin)
        profile_name = st.text_input('Profile name (renaming creates a new version)', value='Custom Profile' if p.builtin else p.profile_name)
        note = st.text_input('Reason / user note (optional; no secrets)')
        result = {'schema_version': 1}
        for name, label in [('general','General'), ('scanner','Scanner'), ('strategies','Strategies'),
                            ('consensus','Consensus'), ('risk','Risk Management'), ('paper_trading','Paper Trading'),
                            ('news','News Intelligence'), ('monitoring','Monitoring')]:
            with st.expander(label, expanded=name in ('strategies','risk')):
                if name == 'strategies':
                    result[name] = {}
                    st.caption('Default weights vary by regime. An override replaces the regime weight in the existing confidence × weight formula.')
                    for item in REGISTRY:
                        st.markdown(f'**{item.display_name}**')
                        config = getattr(draft.strategies, item.strategy_id)
                        values = {}
                        fields = config.model_dump()
                        values['enabled'] = st.checkbox('Enabled', value=config.enabled, key=f'{prefix}.{item.strategy_id}.enabled')
                        override = st.checkbox('Override regime weights', value=config.weight is not None, key=f'{prefix}.{item.strategy_id}.override')
                        weight = st.number_input('Weight', min_value=0.0, value=config.weight if config.weight is not None else 1.0, key=f'{prefix}.{item.strategy_id}.weight')
                        values['weight'] = weight if override else None
                        values['regime_weights'] = edit_model(config.regime_weights, f'{prefix}.{item.strategy_id}.weights')
                        with st.expander(f'{item.display_name} advanced parameters'):
                            st.warning(PARAMETER_WARNING)
                            for param in item.advanced_parameters:
                                value = fields[param]
                                values[param] = st.number_input(param.replace('_',' ').capitalize(), value=value,
                                    step=1 if isinstance(value,int) else 0.1, key=f'{prefix}.{item.strategy_id}.{param}')
                        result[name][item.strategy_id] = values
                else:
                    if name == 'paper_trading':
                        st.info('Base capital is for NEW currency accounts only. Existing ledger capital, balances and trades are never rewritten. Account recapitalization is a separate, future account-management action.')
                    if name == 'risk':
                        st.caption('New position, position-count, portfolio-risk and daily-trade limits require their enforce checkbox. Minimum R:R 0 preserves current admission behavior. Confirmation remains an explicit button action even when the acknowledgement requirement is disabled.')
                    if name == 'news':
                        st.info('Reserved for the future News Intelligence merge. These fields have no effect in V1.')
                    if name == 'monitoring':
                        st.info('Enable Paper monitor and save settings, then run python -m autot.paper_monitor externally. The UI does not start a process. Daily scan remains reserved and has no effect.')
                    if name == 'general':
                        st.caption('RESEARCH has a separate trade identity and performance view. It shares strict real paper-account capital reservations; no extra capital is granted.')
                    result[name] = edit_model(getattr(draft, name), prefix+'.'+name)
        with st.expander('Advanced / Protected execution semantics'):
            st.json(draft.advanced.model_dump())
            st.caption('Read-only in V1. These tested execution semantics cannot be changed here.')
        result['advanced'] = draft.advanced.model_dump()
        saved = st.button('Save Settings')
    st.session_state['settings_draft'] = result
    if saved:
        try:
            if stale_draft:
                raise ValueError('Settings changed in another session. Review the reloaded draft before saving.')
            settings = AutoTSettings.model_validate(result)
            state = store.save(settings, expected_version=state.settings_version, profile_name=profile_name,
                               new_profile=new_profile, reason=note or None)
            st.session_state.pop('settings_draft', None)
            st.session_state['settings_notice'] = f'Saved {state.profile.profile_name} v{state.profile.profile_version}. Run a new scan to use it.'
            st.rerun()
        except (ValidationError, ValueError) as exc:
            st.error(str(exc))
        except Exception:
            st.error('Settings could not be saved. No configuration was activated; check storage and server logs.')
    with st.expander('Settings change history'):
        try:
            st.dataframe(store.history(), hide_index=True)
        except Exception:
            st.warning('Settings history could not be read.')
