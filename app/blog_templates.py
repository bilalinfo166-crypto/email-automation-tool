"""Blog-research outreach templates.

These go to prospects we found through blog research: sites that already have a
link placed on someone else's blog. That link is the whole point — it proves
they're actively building links, so the email opens by naming the exact site and
article we spotted them in.

Writing rules kept to deliberately:
  - always opens "Hi there," (no fake first-name guessing)
  - names the source site AND links the exact article
  - one real pain point, not a list of adjectives
  - the platform is mentioned for credibility, never as something to join
  - ends with a specific question they can answer in one line
  - 100-150 words, plain words, no hype and no pressure

Variables: {{ref_site_name}} {{ref_site}} {{ref_article}} {{company_name}}
           {{sender_name}} {{your_company}} {{your_website}}
"""

COMPANY_FOOTER = """
<br><br>
<div style="border-top:1px solid #e5e7eb;margin-top:20px;padding-top:12px;color:#6b7280;font-size:11px">
<a href="{{unsubscribe_url}}" style="color:#6b7280;font-size:11px;text-decoration:underline">Unsubscribe</a>
</div>
"""

BLOG_TEMPLATES = [
    # 1 — the baseline: spotted you, here's the gap, tell me what you need
    {
        "subject": "Saw your placement on {{ref_site_name}}",
        "body": """Hi there,

I came across a piece on {{ref_site_name}} recently and noticed {{company_name}} linked inside it:
{{ref_article}}

Placements like that don't happen by accident, so I'm guessing link building is already on your roadmap. If so, the part most teams find painful isn't the writing — it's chasing editors, waiting weeks for a reply, and never quite knowing what a fair price looks like.

That's the part we handle. We run {{your_website}}, our own guest posting marketplace, so the sites, metrics and pricing are all ours to show you upfront — nothing hidden, no reseller markup.

You don't have to use the platform though. Most people just tell me what they need and I sort it over email.

What niche are you after, and roughly what budget? I'll come back with a few options.

{{sender_name}}
{{your_company}}""",
    },

    # 2 — short and direct
    {
        "subject": "{{company_name}} on {{ref_site_name}}",
        "body": """Hi there,

Spotted {{company_name}} linked in this {{ref_site_name}} article:
{{ref_article}}

Since you're already placing links, I'll keep this short. We do guest posting on established sites, and we run our own marketplace at {{your_website}} — so you see the site, its metrics and the price before you commit to anything.

No account needed. Tell me the niche and budget you're working with and I'll send back a shortlist.

If the timing's wrong, just say so and I won't follow up.

{{sender_name}}
{{your_company}}""",
    },

    # 3 — pain: paying middlemen
    {
        "subject": "About that {{ref_site_name}} link",
        "body": """Hi there,

I noticed {{company_name}} picked up a link in this piece on {{ref_site_name}}:
{{ref_article}}

Nice placement. The thing I hear most from teams doing this at any scale is that they're rarely sure whether they're buying from the publisher or from three brokers stacked on top of each other — and the price reflects it.

We avoid that by running our own marketplace at {{your_website}}. The sites are ours to offer, so what you're quoted is what it costs.

Happy to work directly over email if that's easier — most people do.

Which niches matter most for {{company_name}} right now?

{{sender_name}}
{{your_company}}""",
    },

    # 4 — pain: slow turnaround
    {
        "subject": "Guest posts for {{company_name}}",
        "body": """Hi there,

Came across {{company_name}} in this {{ref_site_name}} article:
{{ref_article}}

If you're building links steadily, you've probably run into the usual bottleneck: a site says yes, then the draft sits with an editor for three weeks and the campaign stalls.

We keep timelines tight because the sites are on our own platform ({{your_website}}) rather than sourced ad hoc each time. You get a date, and the post goes live on it.

You're welcome to just email me what you need — no need to sign up for anything.

What kind of sites are you looking for at the moment?

{{sender_name}}
{{your_company}}""",
    },

    # 5 — pain: fake metrics
    {
        "subject": "Link placements for {{company_name}}",
        "body": """Hi there,

Saw {{company_name}} mentioned in this {{ref_site_name}} piece:
{{ref_article}}

One thing worth asking about any site you buy from: is the traffic real, or is the DR propped up? Plenty of sellers won't show you, which is how good budgets end up on sites nobody reads.

We show the numbers before you buy — traffic, niche, sample posts. They sit on our own marketplace at {{your_website}}, so we're not repeating someone else's claims.

We work directly too, if you'd rather just email.

Tell me your niche and target metrics and I'll pull a few that genuinely fit.

{{sender_name}}
{{your_company}}""",
    },

    # 6 — question opener
    {
        "subject": "Still building links for {{company_name}}?",
        "body": """Hi there,

Quick question — is {{company_name}} still actively placing guest posts?

I ask because I found this one on {{ref_site_name}}:
{{ref_article}}

If you're still at it, I might be able to make the next batch easier. We place posts on established sites and run our own marketplace at {{your_website}}, so pricing and metrics are visible before anything is agreed.

Plenty of people skip the platform entirely and just tell me what they want over email. Either is fine.

If you've paused link building, no problem — let me know and I'll leave it there.

{{sender_name}}
{{your_company}}""",
    },

    # 7 — helpful, no pitch
    {
        "subject": "Noticed this on {{ref_site_name}}",
        "body": """Hi there,

I was reading through {{ref_site_name}} and saw {{company_name}} referenced here:
{{ref_article}}

I work in guest posting, so I notice these things. Not going to pitch you a package — you clearly already have something running.

The only thing I'd offer: if you ever want a second opinion on what a site should cost, or whether a placement is worth it, I'm happy to look. We run our own marketplace at {{your_website}}, so I see a lot of pricing.

And if you do want placements, we handle those directly over email — no platform sign-up.

Either way, good luck with it.

{{sender_name}}
{{your_company}}""",
    },

    # 8 — scale angle
    {
        "subject": "Scaling past one-off placements",
        "body": """Hi there,

Found {{company_name}} linked in this {{ref_site_name}} article:
{{ref_article}}

One placement is straightforward. Ten a month is where it gets messy — different contacts, different invoices, different quality, and no single view of what's live.

We take that off your plate. Sites come from our own marketplace at {{your_website}}, so you're picking from one list with consistent pricing, and we report back on what went live and where.

If you'd rather keep it simple, email works fine — most clients never touch the platform.

How many placements a month would you realistically want?

{{sender_name}}
{{your_company}}""",
    },

    # 9 — competitor angle
    {
        "subject": "{{company_name}} vs your competitors' link profiles",
        "body": """Hi there,

I spotted {{company_name}} in this piece on {{ref_site_name}}:
{{ref_article}}

Placements like that move the needle, but they only compound if the pace holds. In most niches the sites that outrank everyone aren't doing anything clever — they're just publishing somewhere new every few weeks while everyone else does it twice a year.

We can keep that pace up for you. We run {{your_website}}, our own marketplace, so there's real inventory behind it rather than whatever we can find that month.

Direct over email is completely fine too.

Want me to put together a realistic monthly plan for your niche?

{{sender_name}}
{{your_company}}""",
    },

    # 10 — budget-first
    {
        "subject": "What are you paying per placement?",
        "body": """Hi there,

Noticed {{company_name}} linked in this {{ref_site_name}} article:
{{ref_article}}

Blunt question, and feel free to ignore it: what are you paying per placement at the moment?

I ask because pricing in this space is all over the place — the same site can be quoted three different ways depending on how many hands it passes through.

We list ours openly on {{your_website}}, our own marketplace, so you can compare against whatever you're paying now. If our rates don't beat yours, that's still useful for you to know.

No sign-up needed to get a quote — just reply with a site or two and I'll price them for you.

{{sender_name}}
{{your_company}}""",
    },

    # 11 — reciprocal / peer tone
    {
        "subject": "Fellow link builder",
        "body": """Hi there,

I run guest posting campaigns, so I spend a lot of time reading sites like {{ref_site_name}}. That's where I came across {{company_name}}:
{{ref_article}}

Figured I'd reach out rather than scroll past. If you ever need placements outside your usual contacts — different niche, different region, or just more volume — that's what we do.

We have our own marketplace at {{your_website}}, which mostly means we can show you what we've got instead of asking you to trust a description.

No platform needed if you'd rather deal over email.

What kind of sites are hardest for you to find right now?

{{sender_name}}
{{your_company}}""",
    },

    # 12 — niche relevance angle
    {
        "subject": "Relevant sites for {{company_name}}",
        "body": """Hi there,

Saw {{company_name}} linked here on {{ref_site_name}}:
{{ref_article}}

Good placement — relevance matters more than raw metrics, and that one fits.

The trouble with relevance is supply. Once you've used the obvious sites in a niche, finding the next genuinely relevant one takes real digging, and generic lists don't help.

That's most of what we do. We keep our own inventory on {{your_website}} and add to it constantly, so there's usually something new to offer in a given niche.

Happy to handle it over email — most clients never log in to anything.

Which niche is hardest for you to find sites in?

{{sender_name}}
{{your_company}}""",
    },

    # 13 — short, one question
    {
        "subject": "Placements for {{company_name}}",
        "body": """Hi there,

I found {{company_name}} in this {{ref_site_name}} article:
{{ref_article}}

Short version: we place guest posts on established sites, we run our own marketplace at {{your_website}} so pricing and metrics are transparent, and we're happy to deal directly over email.

One question — what does a good site look like for you? Traffic, niche, budget, whatever matters most.

Send me that and I'll reply with a handful that fit. If none of them work, you've lost two minutes.

{{sender_name}}
{{your_company}}""",
    },

    # 14 — agency angle
    {
        "subject": "If you're placing links for clients",
        "body": """Hi there,

Came across {{company_name}} in this piece on {{ref_site_name}}:
{{ref_article}}

If some of your placements are for clients, the awkward part is usually margin — you need decent sites at a price that still leaves something for you, and most sellers price like they're selling to the end client.

We work with agencies a lot, so that's built in. Our marketplace at {{your_website}} means the inventory is ours, which is what makes the pricing workable.

You don't need to use the platform — plenty of agencies just brief me over email and I handle it.

How many placements a month are you sourcing at the moment?

{{sender_name}}
{{your_company}}""",
    },

    # 15 — soft, low commitment
    {
        "subject": "Two-minute question about {{company_name}}",
        "body": """Hi there,

Saw {{company_name}} linked in this {{ref_site_name}} article and thought I'd reach out:
{{ref_article}}

I'm not going to send you a deck. Just one question: are you happy with where your placements are coming from?

If yes, genuinely, good — ignore this. If there's a gap (price, speed, or the kind of sites you can get), that's what we work on. We run our own marketplace at {{your_website}}, and we handle plenty of it directly over email too.

Either way, a one-line reply is enough and I'll act on it.

{{sender_name}}
{{your_company}}""",
    },

    # 16 — quality control angle
    {
        "subject": "The sites behind your placements",
        "body": """Hi there,

Noticed {{company_name}} in this {{ref_site_name}} piece:
{{ref_article}}

Something worth checking on any site you buy from: how many sponsored posts already sit on it. A page full of obvious paid content is worth far less than the metrics suggest, and it's rarely mentioned upfront.

We vet for that before a site goes on {{your_website}}, our own marketplace. If a site's gone that way, we drop it.

If you'd rather not deal with a platform, just email me your requirements — that works exactly the same.

Want me to sanity-check a couple of sites you're considering? No charge, no obligation.

{{sender_name}}
{{your_company}}""",
    },

    # 17 — ongoing vs one-off
    {
        "subject": "One-off or ongoing?",
        "body": """Hi there,

Found {{company_name}} linked in this article on {{ref_site_name}}:
{{ref_article}}

Curious whether that was a one-off or part of something ongoing.

Reason I ask: the two need completely different setups. One-offs are easy. Ongoing needs a steady supply of sites nobody's overused, which is the part that quietly falls apart around month three.

We keep our own inventory on {{your_website}} and refresh it, which is what makes ongoing workable.

Direct over email is fine if you'd prefer — no sign-up.

Which of the two are you set up for right now?

{{sender_name}}
{{your_company}}""",
    },

    # 18 — no-nonsense pricing
    {
        "subject": "Straight pricing on guest posts",
        "body": """Hi there,

I saw {{company_name}} linked in this {{ref_site_name}} article:
{{ref_article}}

I'll skip the pitch and be useful instead. If you send me two or three sites you're considering, I'll tell you what we'd charge for the same placement. No conditions attached — if we're more expensive, at least you'll know your current rate is good.

We run our own marketplace at {{your_website}}, so the numbers I give you are real ones, not a guess.

And if you'd rather never touch a platform, that's completely fine. Email works.

Send the sites over whenever.

{{sender_name}}
{{your_company}}""",
    },

    # 19 — content quality angle
    {
        "subject": "Who writes your guest posts?",
        "body": """Hi there,

Spotted {{company_name}} in this {{ref_site_name}} piece:
{{ref_article}}

Genuine question — are you writing the posts yourselves, or is that bundled in?

It's the bit that usually decides whether a placement is worth it. A thin, obviously-outsourced article gets buried, and the link goes with it.

We handle writing as part of the placement, and the sites come from our own marketplace at {{your_website}} so we know what each editor will actually accept.

Happy to work directly over email — most people do.

If you tell me your niche, I'll send a sample of what we'd publish for you.

{{sender_name}}
{{your_company}}""",
    },

    # 20 — regional / language angle
    {
        "subject": "Sites outside your usual list",
        "body": """Hi there,

Came across {{company_name}} in this article on {{ref_site_name}}:
{{ref_article}}

Most link profiles I look at are heavily weighted towards the same handful of sites everyone in the niche uses. It still works, but the returns flatten out.

We can widen that — different regions, smaller niche publications, and sites that haven't been used to death. They're on our own marketplace at {{your_website}}, so you can see exactly what you'd be getting.

No platform sign-up needed if you'd rather just brief me.

Any particular market or region you've struggled to get placements in?

{{sender_name}}
{{your_company}}""",
    },

    # 21 — very short
    {
        "subject": "{{ref_site_name}} placement",
        "body": """Hi there,

Saw {{company_name}} linked in this piece on {{ref_site_name}}:
{{ref_article}}

So you're already placing links. The bit that usually slows people down is supply — once the obvious sites in a niche are used up, finding the next decent one takes longer than the placement itself.

We keep our own inventory on {{your_website}}, our marketplace, so there's normally something new to offer rather than the same recycled list. Prices and metrics are shown upfront, nothing second-hand.

There's no need to use the platform. Most people just email me what they want and I handle it from there.

Tell me the niche and rough budget and I'll send a few options. If the timing is wrong, say so and I won't chase.

{{sender_name}}
{{your_company}}""",
    },

    # 22 — trust-first
    {
        "subject": "Before you buy another placement",
        "body": """Hi there,

I noticed {{company_name}} linked in this {{ref_site_name}} article:
{{ref_article}}

Buying links from a stranger over email is a fair thing to be careful about, so here's the short version of who we are: we run {{your_website}}, our own guest posting marketplace. The sites are listed publicly with their metrics, so you can check us before anything is agreed.

Most clients skip the platform and deal with me directly — that's fine either way.

If it's useful, I'll send a couple of live examples in your niche so you can see the standard first.

Want those?

{{sender_name}}
{{your_company}}""",
    },

    # 23 — results / patience angle
    {
        "subject": "Links take a while — worth doing properly",
        "body": """Hi there,

Found {{company_name}} in this piece on {{ref_site_name}}:
{{ref_article}}

Link building is slow, which is exactly why the wrong placements hurt — you don't find out for two or three months, and by then the budget's gone.

We try to reduce that risk by being upfront about what each site actually is. They're all on our own marketplace at {{your_website}}, with metrics you can verify yourself.

Direct over email if you prefer — no account, no platform.

If you tell me what you're targeting, I'll be honest about what's realistic in your niche.

{{sender_name}}
{{your_company}}""",
    },

    # 24 — capacity / volume
    {
        "subject": "Capacity for more placements?",
        "body": """Hi there,

Saw {{company_name}} linked in this {{ref_site_name}} article:
{{ref_article}}

Sounds like the strategy's already working. The usual limit isn't the strategy though — it's how many good sites you can line up without it eating your week.

That's the bit we take on. Our marketplace at {{your_website}} is our own, so supply is steady rather than whatever turns up that month.

You never have to log in to it. Most people email me what they want and it gets handled.

If you could double your placements next month without doubling the admin, would that be useful?

{{sender_name}}
{{your_company}}""",
    },

    # 25 — closing / permission to say no
    {
        "subject": "Worth a conversation?",
        "body": """Hi there,

I came across {{company_name}} in this article on {{ref_site_name}}:
{{ref_article}}

You're clearly already doing link building, so this is either useful timing or completely irrelevant — hard to tell from the outside.

We place guest posts on established sites, run our own marketplace at {{your_website}} so pricing and metrics are visible, and work directly over email for anyone who'd rather skip platforms altogether.

If it's useful: reply with your niche and budget and I'll send options.

If it isn't: reply with "not now" and I'll stop here. No follow-ups.

{{sender_name}}
{{your_company}}""",
    },
]


def get_blog_template(index: int = 0) -> dict:
    """Round-robin through the templates so no two contacts get the same one."""
    return BLOG_TEMPLATES[index % len(BLOG_TEMPLATES)]


def render_blog_template(template: dict, variables: dict) -> dict:
    """Fill in the variables. The footer is added BEFORE substitution so the
    unsubscribe link inside it gets replaced too."""
    subject = template["subject"]
    body = template["body"]
    body_html_raw = body.replace(chr(10), "<br>") + COMPANY_FOOTER
    for key, val in variables.items():
        token = "{{" + key + "}}"
        subject = subject.replace(token, str(val))
        body = body.replace(token, str(val))
        body_html_raw = body_html_raw.replace(token, str(val))
    return {"subject": subject, "body": body, "body_html": body_html_raw}
