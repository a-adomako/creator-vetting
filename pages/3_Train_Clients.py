"""
pages/3_Train_Clients.py — Per-client training (brand context + scoring style).

For each client you can set:
  - Brand context: who they are, who their customer is, what they sell
  - Target niches: which content categories Claude should focus on
  - Special scoring notes: any client-specific rules that don't fit elsewhere
  - Personal scoring style: how YOU evaluate creators for this client

All training data is stored as YAML and markdown files under
knowledge/clients/<client_name>/. These files are also the source the
sync_brand_context_to_spine.py script reads when pushing rubrics into the
central Augmentum database.
"""

import re
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

# ── Paths and imports ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ui_styles import inject as inject_styles

st.set_page_config(page_title="Train Clients — CreatorVetter", layout="wide")
inject_styles()

KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
CLIENTS_DIR = KNOWLEDGE_DIR / "clients"
CLIENTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Page header ──────────────────────────────────────────────────────────────

st.markdown("""
<div class="page-header">
  <div class="page-title">Train Clients</div>
  <div class="page-subtitle">
    Train Claude to vet creators the way you would, per client. Each client
    gets a brand context (who they are and who their audience is), a list of
    target niches, and a personal scoring style (what makes a 9–10 vs a
    deal-breaker for them). The richer the profile, the closer Claude's
    shortlists get to the picks you'd make by hand.
  </div>
</div>
""", unsafe_allow_html=True)

# ── Helpers ──────────────────────────────────────────────────────────────────

def list_clients() -> list[str]:
    return sorted([d.name for d in CLIENTS_DIR.iterdir() if d.is_dir()])


def get_client_dir(name: str) -> Path:
    return CLIENTS_DIR / name


def load_profile(client_name: str) -> dict:
    path = get_client_dir(client_name) / "profile.yaml"
    if path.exists():
        try:
            import yaml
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def save_profile(client_name: str, profile: dict) -> None:
    import yaml
    path = get_client_dir(client_name) / "profile.yaml"
    path.write_text(yaml.dump(profile, allow_unicode=True), encoding="utf-8")


# ── Tabs ─────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs([
    "Your clients (list, create, delete)",
    "Brand context & target niches (per-client briefing)",
    "Your personal scoring style (how you'd judge for them)",
])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — Client list
# ════════════════════════════════════════════════════════════════════════════

with tab1:
    st.markdown(
        '<div class="section-label" style="margin-top:1.5rem;">'
        'Clients you can already train Claude on</div>',
        unsafe_allow_html=True,
    )

    clients = list_clients()
    active = st.session_state.get("active_client")

    if not clients:
        st.info(
            "You don't have any clients trained yet. Create your first one "
            "below — even just a name is enough to start, you can fill in the "
            "details later on the other tabs."
        )
    else:
        for cname in clients:
            profile = load_profile(cname)
            niches = profile.get("target_niches", [])
            niches_str = (
                ", ".join(niches[:3]) + ("…" if len(niches) > 3 else "")
                if niches else "No target niches set yet — open Brand context tab"
            )
            is_active = cname == active

            col_info, col_badge, col_btn = st.columns([4, 1.2, 1], gap="small")
            with col_info:
                st.markdown(
                    f'<div class="client-card{"  client-card-active" if is_active else ""}">'
                    f'<div>'
                    f'<div class="client-name">{cname}</div>'
                    f'<div class="client-meta">{niches_str}</div>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with col_badge:
                if is_active:
                    st.markdown(
                        '<div style="padding-top:6px;">'
                        '<div class="active-badge">● Active</div>'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button(
                        "Set as active",
                        key=f"activate_{cname}",
                        use_container_width=True,
                        help=(
                            f"Make {cname} the active client (the sidebar "
                            f"selector reflects this). The Build Shortlist "
                            f"page defaults to the active client."
                        ),
                    ):
                        st.session_state["active_client"] = cname
                        st.rerun()
            with col_btn:
                if st.button(
                    "Delete",
                    key=f"delete_{cname}",
                    use_container_width=True,
                    type="secondary",
                    help=f"Permanently remove all training data for {cname}",
                ):
                    st.session_state[f"confirm_delete_{cname}"] = True

            if st.session_state.get(f"confirm_delete_{cname}"):
                st.warning(
                    f"Delete client **{cname}** and all their training data "
                    f"(profile.yaml, my_style.md, any examples)? This cannot "
                    f"be undone from the UI."
                )
                dc1, dc2 = st.columns(2)
                with dc1:
                    if st.button(
                        "Yes, delete everything",
                        key=f"confirm_yes_{cname}",
                        type="primary",
                    ):
                        shutil.rmtree(get_client_dir(cname), ignore_errors=True)
                        if st.session_state.get("active_client") == cname:
                            st.session_state["active_client"] = None
                        st.session_state.pop(f"confirm_delete_{cname}", None)
                        st.rerun()
                with dc2:
                    if st.button("Cancel — keep this client", key=f"confirm_no_{cname}"):
                        st.session_state.pop(f"confirm_delete_{cname}", None)
                        st.rerun()

    st.markdown('<div style="height:1.5rem;"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-label">Create a new client we can train Claude on</div>',
        unsafe_allow_html=True,
    )

    with st.form("new_client_form"):
        new_name = st.text_input(
            "Client name (also used as the folder name in knowledge/clients/)",
            placeholder="e.g. Kloris, Elavate, Mother's Earth, AG1",
            help=(
                "Letters, numbers, hyphens, and underscores only — anything else "
                "is replaced with an underscore so the folder name stays "
                "filesystem-safe."
            ),
        )
        create_clicked = st.form_submit_button(
            "Create this client", type="primary"
        )

    if create_clicked:
        safe_name = re.sub(r"[^\w\-]", "_", new_name.strip())
        if not safe_name:
            st.error(
                "Please enter a client name. It needs at least one letter, "
                "number, hyphen, or underscore."
            )
        elif (CLIENTS_DIR / safe_name).exists():
            st.warning(
                f"A client named **{safe_name}** already exists in "
                f"knowledge/clients/. Edit it from the list above instead."
            )
        else:
            (CLIENTS_DIR / safe_name).mkdir(parents=True, exist_ok=True)
            save_profile(safe_name, {
                "brand_context": "", "target_niches": [], "scoring_notes": "",
            })
            st.session_state["active_client"] = safe_name
            st.success(
                f"Client **{safe_name}** created and set as active. "
                f"Now open the **Brand context & target niches** tab "
                f"to fill in the details."
            )
            st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — Brand context & target niches
# ════════════════════════════════════════════════════════════════════════════

with tab2:
    active = st.session_state.get("active_client")
    clients = list_clients()

    if not clients:
        st.info(
            "Create your first client on the **Your clients** tab — then come "
            "back here to fill in their brand context and target niches."
        )
    elif not active or active not in clients:
        st.warning(
            "No client is set as active. Open the **Your clients** tab and "
            "click **Set as active** on the one you want to train, or use the "
            "sidebar selector."
        )
    else:
        st.markdown(
            f'<div style="margin:1.5rem 0 1.25rem;">'
            f'<span style="font-size:0.75rem;font-weight:600;letter-spacing:0.08em;'
            f'text-transform:uppercase;color:#5A5A60;">Editing brand context for: </span>'
            f'<span style="font-size:0.9375rem;font-weight:700;color:#FF1F8E;">{active}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        profile = load_profile(active)

        NICHE_OPTIONS = [
            "Health & Wellness", "Fitness", "Beauty & Skincare", "Lifestyle",
            "Food & Beverage", "Fashion", "Nutrition", "Mental Health",
            "Parenting", "Travel", "Home & Decor", "Sustainability",
            "Menopause", "Sleep & Recovery", "Nature & Country Lifestyle",
            "Equestrian", "Busy Professionals", "Health Educators",
        ]

        with st.form("profile_form"):
            brand_context = st.text_area(
                "Brand context — who this client is, what they sell, and who their customer is",
                value=profile.get("brand_context", ""),
                height=180,
                placeholder=(
                    "Describe the brand and their audience as if briefing a new "
                    "team member. Include:\n"
                    "  • What the brand sells and what makes it premium / specific\n"
                    "  • Who the target customer is (age, income, lifestyle, values)\n"
                    "  • Any recent strategic pivots in who they want to reach\n"
                    "  • Reference creators they've loved working with\n\n"
                    "Example: KLORIS is a premium UK wellness brand selling sleep "
                    "patches, face oils, and CBD-derived recovery products. Originally "
                    "CBD-led, repositioned April 2026 as broader premium botanical "
                    "wellness. Target: women 35+ with disposable income, calm aesthetic, "
                    "trust-led creators not deal-led ones."
                ),
                help=(
                    "This text is injected into every Claude prompt that scores a "
                    "creator for this client. The more specific you are, the more "
                    "Claude's reasoning will reference what you actually care about."
                ),
            )

            existing_niches = profile.get("target_niches", [])
            valid_existing = [n for n in existing_niches if n in NICHE_OPTIONS]
            custom_existing = [n for n in existing_niches if n not in NICHE_OPTIONS]

            selected_niches = st.multiselect(
                "Target niches (Claude focuses its evaluation on these)",
                options=NICHE_OPTIONS,
                default=valid_existing,
                help=(
                    "Pick every niche that's relevant for this client. Claude uses "
                    "these to weigh whether a creator's primary content matches. "
                    "Add custom niches in the box below if your client cares about "
                    "something not in this list."
                ),
            )

            custom_niches_str = st.text_input(
                "Additional niches not in the dropdown above (comma-separated)",
                value=", ".join(custom_existing),
                placeholder="e.g. Biohacking, Longevity, Equestrian, Hormone Balance",
                help=(
                    "Type anything that's relevant but not standard. These get "
                    "added to the niche list alongside what you picked above."
                ),
            )

            scoring_notes = st.text_area(
                "Special scoring notes — any client-specific rules that don't fit elsewhere",
                value=profile.get("scoring_notes", ""),
                height=120,
                placeholder=(
                    "Anything client-specific that isn't covered by brand context "
                    "or scoring style. Examples:\n"
                    "  • Micro-influencers only (under 100k followers)\n"
                    "  • No fitness creators — strictly nutrition and wellness\n"
                    "  • UK primary, EU acceptable, US out-of-brief\n"
                    "  • Phase out chronic-illness niches per client decision"
                ),
                help=(
                    "Hard rules that should never be broken. Goes into Claude's "
                    "system prompt for this client."
                ),
            )

            save_profile_clicked = st.form_submit_button(
                "Save brand context and target niches",
                type="primary",
            )

        if save_profile_clicked:
            custom_list = [n.strip() for n in custom_niches_str.split(",") if n.strip()]
            all_niches = selected_niches + custom_list
            new_profile = {
                "brand_context": brand_context.strip(),
                "target_niches": all_niches,
                "scoring_notes": scoring_notes.strip(),
            }
            save_profile(active, new_profile)
            st.success(
                f"Saved brand context for **{active}**. The next time you run "
                f"**Build Shortlist** against this client, Claude will use the "
                f"updated profile."
            )


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — Personal scoring style
# ════════════════════════════════════════════════════════════════════════════

with tab3:
    active = st.session_state.get("active_client")
    clients = list_clients()

    if not clients:
        st.info(
            "Create your first client on the **Your clients** tab — then come "
            "back here to write your personal scoring style for them."
        )
    elif not active or active not in clients:
        st.warning(
            "No client is set as active. Open the **Your clients** tab and "
            "click **Set as active** on the one you want to train."
        )
    else:
        st.markdown(
            f'<div style="margin:1.5rem 0 1rem;">'
            f'<span style="font-size:0.75rem;font-weight:600;letter-spacing:0.08em;'
            f'text-transform:uppercase;color:#5A5A60;">Editing personal scoring style for: </span>'
            f'<span style="font-size:0.9375rem;font-weight:700;color:#FF1F8E;">{active}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        style_path = get_client_dir(active) / "my_style.md"
        existing_style = (
            style_path.read_text(encoding="utf-8") if style_path.exists() else ""
        )

        st.markdown("""
        <div class="style-guide-wrap">
          <div style="font-size:0.875rem;font-weight:600;color:#1D1D1F;margin-bottom:0.75rem;">
            Think of this as your personal brief to Claude. Write how you actually
            evaluate creators for this client — the more specific you are about
            what you weigh and why, the more Claude's picks will match yours.
          </div>
          <div class="guide-question">→ What makes a 9–10/10 creator for this client?</div>
          <div class="guide-question">→ What are your absolute deal-breakers (instant disqualify)?</div>
          <div class="guide-question">→ How do you weight authenticity vs engagement vs production quality?</div>
          <div class="guide-question">→ Any size preferences (nano, micro, mid-tier)?</div>
          <div class="guide-question">→ What content styles or themes resonate most?</div>
          <div class="guide-question">→ What content styles don't work, even when other signals look good?</div>
        </div>
        """, unsafe_allow_html=True)

        _STYLE_STARTER = """\
## How I evaluate creators for this client

**What makes a great fit (9–10/10):**
-

**Deal-breakers (instant disqualify):**
-

**How I weight signals:**
- Authenticity: most important — I care more about genuine voice than follower count
- Engagement: solid signal but not everything
- Production quality: nice to have, not required

**Size preference:**
-

**Content styles that work:**
-

**Content styles that don't work:**
-
"""

        new_style = st.text_area(
            "Personal scoring style for this client (markdown supported)",
            value=existing_style if existing_style else _STYLE_STARTER,
            height=420,
            label_visibility="collapsed",
        )

        save_col, clear_col = st.columns([3, 1])
        with save_col:
            if st.button(
                "Save personal scoring style for this client",
                type="primary",
                use_container_width=True,
            ):
                style_path.write_text(new_style, encoding="utf-8")
                st.success(
                    f"Saved your scoring style for **{active}**. Every shortlist "
                    f"built against this client will now reflect how you'd judge "
                    f"creators."
                )
        with clear_col:
            if st.button(
                "Clear and start over",
                use_container_width=True,
                type="secondary",
                help="Wipe the current scoring style for this client",
            ):
                style_path.write_text("", encoding="utf-8")
                st.rerun()

        if existing_style:
            st.markdown(
                '<p style="font-size:0.75rem;color:#5A5A60;margin-top:0.5rem;">'
                'The content shown above is the current saved version. Edit in '
                'place and click <strong>Save</strong>.'
                '</p>',
                unsafe_allow_html=True,
            )

# ── Navigation footer ───────────────────────────────────────────────────────

st.markdown('<div style="height:2.5rem;"></div>', unsafe_allow_html=True)
st.markdown("""
<div style="border-top:1px solid #E5E5EA;padding-top:1.25rem;">
  <span style="font-size:0.75rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#5A5A60;">Go to</span>
</div>
""", unsafe_allow_html=True)
_tf1, _tf2 = st.columns(2)
with _tf1:
    st.page_link(
        "pages/1_Vet_Creators.py",
        label="Vet Creators — run the pipeline on a new CSV",
        icon="▶",
    )
with _tf2:
    st.page_link(
        "pages/2_Build_Shortlist.py",
        label="Build Shortlist — filter the latest CSV against this client",
        icon="🎯",
    )
