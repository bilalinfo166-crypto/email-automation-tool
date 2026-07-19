"""50 Guest Posting & Link Building Outreach Templates.
Research-based: max 100 words, starts "Hi there,", first-name signature,
subject mentions client site, SEO/link-building focused.
Round-robin: email #1 -> template 1, #50 -> template 50, #51 -> template 1.
"""

COMPANY_FOOTER = """
<div style="margin-top:24px;font-family:Arial,sans-serif">
<div style="text-align:center;margin-bottom:12px">
<a href="{{unsubscribe_url}}" style="color:#6b7280;font-size:11px;text-decoration:underline">Unsubscribe</a>
</div>
<div style="padding-top:10px;border-top:1px solid #e5e7eb;font-size:11px;color:#9ca3af">
<b style="color:#1a1a2e;font-size:12px">Uplyncio.com</b><br>
<span style="color:#9ca3af">Guest Posting & Niche Edit Platform</span><br>
<a href="mailto:info@uplyncio.com" style="color:#4f46e5;text-decoration:none;font-size:11px">info@uplyncio.com</a>
</div></div>"""

TEMPLATES = [
    {"subject": 'Guest post idea for {{website}}',
     "body": 'Hi there,\n\nI run guest posting campaigns and came across {{company_name}}. I can get you published on relevant, high-authority sites in your niche — with natural backlinks that improve your Google rankings.\n\nEvery placement is on a real site with genuine traffic, and I handle the writing and outreach end to end.\n\nWant me to share a few sites where {{company_name}} could get featured?\n\nBest,\n{{sender_name}}'},
    {"subject": "Boosting {{website}}'s search rankings",
     "body": 'Hi there,\n\nI help sites like {{company_name}} earn quality backlinks through guest posts on trusted industry websites. These links build your domain authority and push your pages higher on Google.\n\nNo link farms, no spam — just real placements on real sites.\n\nWould you like to see a few options?\n\nThanks,\n{{sender_name}}'},
    {"subject": 'SEO backlinks for {{website}}',
     "body": 'Hi there,\n\nI noticed {{company_name}} and wanted to reach out. I place guest articles on established websites in your niche, each with a natural link back to your site.\n\nThis is one of the most reliable ways to grow organic traffic and improve search rankings.\n\nShall I send you a short list of sites we could target?\n\nBest,\n{{sender_name}}'},
    {"subject": "Quick idea to grow {{website}}'s traffic",
     "body": 'Hi there,\n\nQuick one — I build backlinks for businesses like {{company_name}} through guest posting on authority sites. Better links mean better rankings and more organic traffic over time.\n\nI take care of the content and the outreach; you just approve.\n\nInterested in seeing what sites would fit {{company_name}}?\n\nCheers,\n{{sender_name}}'},
    {"subject": 'Link building for {{website}}',
     "body": "Hi there,\n\nI specialise in link building through guest posts and thought {{company_name}} would be a great fit. I get you featured on relevant sites with strong domain authority, earning links that lift your Google rankings.\n\nEverything's white-hat and handled for you.\n\nWant a few example sites?\n\nBest,\n{{sender_name}}"},
    {"subject": 'Featured articles for {{website}}',
     "body": "Hi there,\n\nI help brands like {{company_name}} get quality backlinks through guest articles on niche-relevant websites. It's a proven way to boost search rankings and bring in steady organic traffic.\n\nI manage writing, outreach, and placement start to finish.\n\nShall I share a few sites we could target for you?\n\nThanks,\n{{sender_name}}"},
    {"subject": "Improving {{website}}'s domain authority",
     "body": 'Hi there,\n\nI came across {{company_name}} while looking at sites in your niche. I run guest posting campaigns that earn real backlinks from trusted websites — the kind that actually move rankings.\n\nNo shortcuts, just quality placements.\n\nWould you be open to a few site suggestions?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Guest posting partnership — {{website}}',
     "body": 'Hi there,\n\nI place guest posts on high-authority websites to help sites like {{company_name}} rank higher and grow organic traffic. Each link is editorial, relevant, and built to last.\n\nI handle everything — you only review the final article.\n\nWant to see a few options for {{company_name}}?\n\nCheers,\n{{sender_name}}'},
    {"subject": "Grow {{website}}'s organic traffic",
     "body": "Hi there,\n\nI build backlinks through guest posting and think {{company_name}} could benefit. I get your brand featured on real sites in your niche, with links that strengthen your SEO and rankings.\n\nEverything's done for you, white-hat only.\n\nCan I send a short list of target sites?\n\nBest,\n{{sender_name}}"},
    {"subject": 'Backlink opportunities for {{website}}',
     "body": 'Hi there,\n\nI help businesses like {{company_name}} grow through guest posts and link building. These placements earn quality backlinks that improve your domain authority and Google rankings.\n\nI take care of research, writing, and outreach.\n\nWould a few example sites be useful?\n\nThanks,\n{{sender_name}}'},
    {"subject": 'Content + links for {{website}}',
     "body": 'Hi there,\n\nI run link building campaigns and wanted to reach out about {{company_name}}. I can get you guest posts on relevant, authoritative sites — each with a natural backlink that boosts your rankings.\n\nAll placements are on genuine sites with real traffic.\n\nShall I share a few options?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Ranking {{website}} higher on Google',
     "body": 'Hi there,\n\nContent plus backlinks is one of the best ways to grow search traffic. I help sites like {{company_name}} do exactly that through guest posts on trusted niche websites.\n\nI handle the writing and outreach; you approve and we publish.\n\nWant to see where {{company_name}} could be featured?\n\nCheers,\n{{sender_name}}'},
    {"subject": 'Guest articles to promote {{website}}',
     "body": 'Hi there,\n\nI help {{company_name}}-type sites climb Google through guest posting and quality link building. Real placements, real sites, real ranking improvements.\n\nNo spam, no automation — just white-hat outreach done properly.\n\nInterested in a few target site suggestions?\n\nBest,\n{{sender_name}}'},
    {"subject": 'SEO growth idea for {{website}}',
     "body": "Hi there,\n\nI write and place guest articles on authority websites to promote brands like {{company_name}}. Each article includes a natural link that helps your SEO and drives referral traffic.\n\nEverything's handled end to end.\n\nWould you like a short list of sites for {{company_name}}?\n\nThanks,\n{{sender_name}}"},
    {"subject": 'Quality backlinks for {{website}}',
     "body": 'Hi there,\n\nSEO growth comes down to quality backlinks — and I build them through guest posting for sites like {{company_name}}. Placements on relevant, trusted websites that lift your rankings over time.\n\nI manage the whole process for you.\n\nCan I share a few site options?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Getting {{website}} more visibility',
     "body": 'Hi there,\n\nI earn quality backlinks for businesses like {{company_name}} through guest posts on niche-relevant sites. These links improve domain authority and help you rank for the terms that matter.\n\nWhite-hat only, fully managed.\n\nWant to see what sites would fit {{company_name}}?\n\nCheers,\n{{sender_name}}'},
    {"subject": 'Guest post collaboration — {{website}}',
     "body": 'Hi there,\n\nI help sites like {{company_name}} get more visibility through guest posting on established websites. Each placement earns a backlink that strengthens your SEO and brings in new visitors.\n\nI handle content and outreach; you just approve.\n\nShall I send a few example sites?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Link building idea for {{website}}',
     "body": "Hi there,\n\nI'd love to collaborate with {{company_name}} on guest posts. I place articles on trusted niche sites, each with a natural backlink that boosts your Google rankings.\n\nReal sites, real traffic, white-hat throughout.\n\nWould a few target site ideas help?\n\nThanks,\n{{sender_name}}"},
    {"subject": 'Featured placements for {{website}}',
     "body": "Hi there,\n\nHere's a simple idea for {{company_name}} — guest posts on authority websites with backlinks that improve your rankings. It's one of the most dependable SEO strategies out there.\n\nI take care of everything from writing to placement.\n\nWant to explore a few options?\n\nBest,\n{{sender_name}}"},
    {"subject": 'Growing {{website}} with guest posts',
     "body": 'Hi there,\n\nI help brands like {{company_name}} earn featured placements on relevant websites, each with a quality backlink. Over time this grows your organic traffic and search visibility.\n\nFully managed, white-hat only.\n\nCan I share a short list of sites?\n\nCheers,\n{{sender_name}}'},
    {"subject": 'SEO backlinks — {{website}}',
     "body": 'Hi there,\n\nI grow sites like {{company_name}} through guest posting and link building. My placements are on real, trusted websites in your niche — the kind of backlinks Google actually rewards.\n\nI handle the work; you approve the results.\n\nInterested in a few site suggestions?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Traffic idea for {{website}}',
     "body": "Hi there,\n\nQuality backlinks still drive rankings, and I build them for sites like {{company_name}} through guest posts on authority websites. Each link is editorial and relevant to your niche.\n\nEverything's handled for you.\n\nShall I send a few target sites?\n\nThanks,\n{{sender_name}}"},
    {"subject": 'Guest posting for {{website}}',
     "body": 'Hi there,\n\nI can help {{company_name}} get more organic traffic through guest posting. I place articles on trusted sites with natural backlinks that improve your search rankings.\n\nNo spam, just white-hat outreach done well.\n\nWant to see where you could be featured?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Authority links for {{website}}',
     "body": 'Hi there,\n\nI run guest posting for businesses like {{company_name}}. I get you published on relevant, high-authority websites, earning backlinks that lift your rankings and drive referral traffic.\n\nWriting and outreach handled end to end.\n\nCan I share a few options?\n\nCheers,\n{{sender_name}}'},
    {"subject": 'Helping {{website}} rank higher',
     "body": 'Hi there,\n\nI build authority backlinks for sites like {{company_name}} through guest articles on niche websites. These links strengthen your SEO and push your pages higher on Google.\n\nWhite-hat, fully managed.\n\nWould a short list of target sites help?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Content marketing for {{website}}',
     "body": 'Hi there,\n\nI help {{company_name}} rank higher through guest posts on trusted industry sites. Each placement includes a natural backlink that improves your domain authority over time.\n\nI take care of the whole process for you.\n\nWant a few example sites?\n\nThanks,\n{{sender_name}}'},
    {"subject": 'Guest post outreach — {{website}}',
     "body": "Hi there,\n\nContent marketing plus link building is how sites like {{company_name}} grow search traffic. I place guest articles on relevant authority sites with backlinks that boost rankings.\n\nEverything's done for you, white-hat only.\n\nShall I share some target sites?\n\nBest,\n{{sender_name}}"},
    {"subject": 'Backlinks to grow {{website}}',
     "body": 'Hi there,\n\nI place guest posts for brands like {{company_name}} on established websites in your niche. The backlinks earn you better rankings and steady organic traffic.\n\nI handle writing, outreach, and publishing.\n\nInterested in a few site options?\n\nCheers,\n{{sender_name}}'},
    {"subject": 'SEO idea worth sharing — {{website}}',
     "body": 'Hi there,\n\nI earn quality backlinks for {{company_name}}-type sites through guest posting. Real placements on trusted websites — the kind that genuinely move search rankings.\n\nNo automation, no link farms, fully managed.\n\nWant to see a short list of sites?\n\nBest,\n{{sender_name}}'},
    {"subject": "Building {{website}}'s backlink profile",
     "body": "Hi there,\n\nHere's an SEO idea for {{company_name}} — guest posts on authority sites with backlinks that improve rankings. It's one of the most effective ways to grow organic traffic.\n\nI take care of everything for you.\n\nCan I share a few target sites?\n\nThanks,\n{{sender_name}}"},
    {"subject": 'Guest articles for {{website}}',
     "body": 'Hi there,\n\nI help build strong backlink profiles for sites like {{company_name}} through guest posting on niche-relevant websites. Better links, better rankings, more traffic.\n\nWhite-hat and fully managed.\n\nWould you like to see some options?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Rankings boost for {{website}}',
     "body": 'Hi there,\n\nI write and place guest articles to promote sites like {{company_name}}. Each article earns a natural backlink that boosts your SEO and brings in relevant visitors.\n\nEnd-to-end, handled for you.\n\nShall I send a few example sites?\n\nCheers,\n{{sender_name}}'},
    {"subject": 'Quality guest posts — {{website}}',
     "body": 'Hi there,\n\nI help {{company_name}} climb Google through guest posts and quality link building. Placements on real, trusted sites that improve your rankings for the long term.\n\nWhite-hat outreach done properly.\n\nWant a short list of target sites?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Link building partnership — {{website}}',
     "body": 'Hi there,\n\nQuality guest posts still deliver the best backlinks, and I build them for sites like {{company_name}}. Relevant placements on authority websites that lift your search visibility.\n\nI handle content and outreach for you.\n\nInterested in a few options?\n\nThanks,\n{{sender_name}}'},
    {"subject": "Grow {{website}}'s search presence",
     "body": "Hi there,\n\nI'd love to partner with {{company_name}} on link building. I place guest articles on trusted niche sites, each with a backlink that improves your Google rankings.\n\nReal sites, white-hat, fully managed.\n\nCan I share a few target sites?\n\nBest,\n{{sender_name}}"},
    {"subject": 'Featured content for {{website}}',
     "body": 'Hi there,\n\nI help sites like {{company_name}} grow their search presence through guest posts on authority websites. Each placement earns a quality backlink that boosts rankings and traffic.\n\nWriting and outreach handled end to end.\n\nWant to see where you could be featured?\n\nCheers,\n{{sender_name}}'},
    {"subject": 'SEO backlink idea — {{website}}',
     "body": 'Hi there,\n\nI place featured guest content for brands like {{company_name}} on relevant, trusted sites. The backlinks improve your domain authority and help you rank higher.\n\nFully managed, white-hat only.\n\nShall I send a short list of sites?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Guest post placements — {{website}}',
     "body": "Hi there,\n\nHere's a backlink idea for {{company_name}} — guest posts on authority websites in your niche. Each link strengthens your SEO and pushes your pages higher on Google.\n\nI take care of the whole process.\n\nWant a few example sites?\n\nThanks,\n{{sender_name}}"},
    {"subject": "Boosting {{website}}'s SEO",
     "body": 'Hi there,\n\nI get sites like {{company_name}} published on trusted websites through guest posting. The natural backlinks improve rankings and drive relevant organic traffic.\n\nNo spam, white-hat throughout.\n\nCan I share a few target sites for you?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Traffic + backlinks for {{website}}',
     "body": 'Hi there,\n\nI help boost SEO for businesses like {{company_name}} through guest posts and link building on niche-relevant sites. Quality backlinks that Google actually values.\n\nEverything handled for you.\n\nWould a short list of options help?\n\nCheers,\n{{sender_name}}'},
    {"subject": 'Guest posting idea — {{website}}',
     "body": 'Hi there,\n\nI combine guest posting with quality backlinks to grow traffic for sites like {{company_name}}. Placements on real authority sites that lift your rankings over time.\n\nWhite-hat and fully managed.\n\nWant to see a few site options?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Helping {{website}} grow online',
     "body": "Hi there,\n\nHere's a guest posting idea for {{company_name}} — featured articles on trusted niche sites, each with a backlink that improves your search rankings.\n\nI handle the writing and outreach; you just approve.\n\nShall I share a short list of sites?\n\nThanks,\n{{sender_name}}"},
    {"subject": 'Backlink strategy for {{website}}',
     "body": 'Hi there,\n\nI help sites like {{company_name}} grow online through guest posts and link building. Real placements on authority websites, earning backlinks that boost your rankings.\n\nFully managed, white-hat only.\n\nInterested in a few target sites?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Guest articles + SEO — {{website}}',
     "body": 'Hi there,\n\nI build backlink strategies for businesses like {{company_name}} through guest posting on relevant, trusted sites. Better links mean better rankings and more organic traffic.\n\nI take care of everything for you.\n\nWant to see some options?\n\nCheers,\n{{sender_name}}'},
    {"subject": 'Ranking idea for {{website}}',
     "body": 'Hi there,\n\nI place guest articles with SEO backlinks for sites like {{company_name}}. Each link is editorial, relevant, and built to improve your Google rankings.\n\nWhite-hat outreach, fully managed.\n\nCan I send a few target sites?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Link building for your site {{website}}',
     "body": "Hi there,\n\nHere's a ranking idea for {{company_name}} — guest posts on authority websites with natural backlinks. It's one of the most reliable ways to grow search traffic.\n\nI handle the whole process end to end.\n\nWould a short list of sites help?\n\nThanks,\n{{sender_name}}"},
    {"subject": 'Guest post opportunity — {{website}}',
     "body": 'Hi there,\n\nI do link building through guest posts for sites like {{company_name}}. I get you featured on trusted niche websites, each with a backlink that lifts your rankings.\n\nReal sites, white-hat, done for you.\n\nWant a few example sites?\n\nBest,\n{{sender_name}}'},
    {"subject": 'SEO growth for {{website}}',
     "body": "Hi there,\n\nI'd love to help {{company_name}} with a guest post opportunity. I place articles on relevant authority sites with backlinks that improve your SEO and drive traffic.\n\nEverything handled end to end.\n\nShall I share some target sites?\n\nCheers,\n{{sender_name}}"},
    {"subject": 'Quality links for {{website}}',
     "body": 'Hi there,\n\nI help grow SEO for sites like {{company_name}} through guest posting on trusted websites. Quality backlinks that boost rankings and bring in organic visitors.\n\nWhite-hat, fully managed.\n\nInterested in a short list of sites?\n\nBest,\n{{sender_name}}'},
    {"subject": 'Guest posting to grow {{website}}',
     "body": 'Hi there,\n\nI build quality links for brands like {{company_name}} through guest posts on niche-relevant sites. These backlinks strengthen your domain authority and rankings.\n\nI handle writing and outreach for you.\n\nWant to see where {{company_name}} could be featured?\n\nThanks,\n{{sender_name}}'},
]


def get_template(index: int) -> dict:
    return TEMPLATES[index % len(TEMPLATES)]


def render_template(template: dict, variables: dict) -> dict:
    subject = template["subject"]
    body = template["body"]
    for key, val in variables.items():
        subject = subject.replace("{{" + key + "}}", str(val))
        body = body.replace("{{" + key + "}}", str(val))
    body_html = body.replace(chr(10), "<br>") + COMPANY_FOOTER
    return {"subject": subject, "body": body, "body_html": body_html}
