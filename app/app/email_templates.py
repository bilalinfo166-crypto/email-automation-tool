"""50 Guest Posting Outreach Templates — Professional, detailed, clear purpose.
Round-robin: email #1 gets template 1, #50 gets template 50, #51 gets template 1 again.
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
    # 1-10: Clear intro + purpose
    {"subject": "Guest post for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI came across {{company_name}} ({{website}}) and was impressed by what you've built. I'm reaching out because we help businesses like yours get featured through professionally written guest posts on established, niche-relevant websites.\n\nThe idea is simple — we write a high-quality article about a topic relevant to {{company_name}}, and get it published on a trusted website in {{industry}}. This gives your brand exposure to a new, relevant audience and builds your online authority.\n\nWe handle the entire process — topic research, writing, editing, and publishing. You just review and approve.\n\nWould you be open to seeing a few site options where {{company_name}} could be featured?\n\nBest regards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Get {{company_name}} on {{industry}} websites",
     "body": "Hi {{first_name}},\n\nI recently visited {{website}} and thought I'd reach out with a quick idea.\n\nWe specialize in placing guest articles on well-known websites within {{industry}}. These aren't generic directory listings — they're carefully written, editorial-style articles that position your brand as an authority in your space.\n\nHere's how it works:\n— We identify relevant publications that your target audience reads\n— We write a custom article featuring {{company_name}}\n— The article gets published with a natural mention and link back to your site\n\nIt's a proven way to build trust and reach new customers. Would you like me to share a few options?\n\nKind regards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{first_name}}, a guest article idea for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI'm {{sender_name}} from Uplyncio. We work with businesses in {{industry}} to help them get published on reputable industry websites through guest articles.\n\nI noticed {{company_name}} at {{website}} and believe your brand would be a great fit for some of the publications we work with. Getting featured on these sites can significantly boost your credibility and bring in qualified traffic.\n\nWe take care of everything — from topic selection to the final published piece. All content is original, relevant, and written to a high standard.\n\nShall I put together a shortlist of sites where {{company_name}} could appear?\n\nCheers,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Editorial placement for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI wanted to reach out because I think there's a valuable opportunity for {{company_name}}.\n\nWe help brands get featured on established websites through professionally written guest posts. Think of it as getting your brand mentioned in the right places — websites that your potential customers already trust and read.\n\nFor {{company_name}}, we could place articles on relevant sites in {{industry}}, each featuring your brand naturally and linking back to {{website}}.\n\nThe process is simple: we write, we place, you approve. No hassle on your end.\n\nInterested in seeing what's available?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on {{industry}} publications?",
     "body": "Hi {{first_name}},\n\nI'm writing from Uplyncio, a guest posting and niche edit platform. We help businesses like {{company_name}} build their online presence by getting them featured on trusted, niche-relevant websites.\n\nHere's what we offer:\n— Custom-written guest articles tailored to your brand\n— Placement on real, established websites in {{industry}}\n— Natural backlinks to {{website}} that boost your SEO\n— Full service: we handle writing, outreach, and publishing\n\nMany businesses in your space are already using this approach to build credibility and attract new customers.\n\nWould it make sense to share a few site options?\n\nRegards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Publishing {{company_name}} on industry websites",
     "body": "Hi {{first_name}},\n\nI visited {{website}} and was curious — has {{company_name}} ever considered getting featured on popular industry websites through guest articles?\n\nWe help businesses do exactly this. We write high-quality, relevant articles and get them published on established websites in {{industry}}. Each article naturally mentions your brand and links back to your site.\n\nIt's one of the most effective ways to build authority and reach new audiences online.\n\nI'd be happy to explain more or share some examples if you're interested.\n\nThanks,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest article idea for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI came across {{company_name}} while researching businesses in {{industry}}, and I thought this might interest you.\n\nWe help brands get editorial coverage on well-known websites through guest content. This means a professionally written article about a topic related to your business, published on a trusted site that your audience reads.\n\nThe result? More visibility, more credibility, and quality traffic back to {{website}}.\n\nWe handle everything from start to finish. Would you be open to exploring this?\n\nBest regards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Content placement for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI'll keep this brief. We help businesses like {{company_name}} get featured articles published on reputable websites in {{industry}}.\n\nEach article is:\n— Original and well-researched\n— Relevant to your brand and audience\n— Published on a real, trusted website\n— Includes a natural link back to {{website}}\n\nWe do all the work — you just approve the final piece.\n\nWant me to send over a few site options that would be a good fit?\n\nCheers,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{first_name}}, guest post idea for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI was looking at {{website}} and wanted to suggest something that could benefit {{company_name}}.\n\nWe connect businesses with established online publications for guest article placements. The idea is to get your brand in front of the right audience through well-written content on websites they already trust.\n\nThis approach has helped many businesses in {{industry}} build stronger online authority and drive relevant traffic.\n\nI'd love to discuss how this could work for {{company_name}}. Open to a quick conversation?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Get {{company_name}} on relevant industry websites",
     "body": "Hi {{first_name}},\n\nI'm reaching out because I believe {{company_name}} could benefit from a content placement strategy that many successful businesses in {{industry}} are using.\n\nThe concept is straightforward: we write expert-level articles about topics related to your business, and place them on established websites that your target audience reads. Each article features {{company_name}} naturally and links back to {{website}}.\n\nThis builds trust, visibility, and SEO value — all without any effort on your end.\n\nShall I share some relevant publication options?\n\nKind regards,\n{{sender_name}}\nUplyncio.com"},

    # 11-20: Value-focused
    {"subject": "{{first_name}}, a thought about {{company_name}}",
     "body": "Hi {{first_name}},\n\nAfter visiting {{website}}, I noticed {{company_name}} has strong potential to reach a much wider audience online.\n\nOne of the most effective ways to do this is through guest article placements on established industry websites. We write a compelling article related to your business, get it published on a relevant website, and include a natural mention of {{company_name}}.\n\nThe result is increased brand visibility, stronger credibility, and new traffic from readers who are already interested in {{industry}}.\n\nWould you like me to put together a few tailored options?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Article placement for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI work with Uplyncio, where we help businesses in {{industry}} strengthen their online presence through strategic guest post placements.\n\nThe process is simple: we identify the best publications for your brand, create high-quality content that features {{company_name}}, and handle the entire publishing process.\n\nMany businesses similar to yours have seen measurable improvements in brand awareness and website traffic within 60-90 days.\n\nWant to see what kind of placements would work for {{company_name}}?\n\nThanks,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on {{industry}} websites",
     "body": "Hi {{first_name}},\n\nCredibility matters in {{industry}}, and one of the best ways to build it is by getting featured on respected industry websites.\n\nWe help businesses like {{company_name}} achieve this through carefully placed guest articles. Each article is written by professional writers, tailored to your brand, and published on a real website that your audience trusts.\n\nIt's not about mass link building — it's about strategic, quality placements that position {{company_name}} as an authority.\n\nInterested in learning more?\n\nBest regards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest post idea — {{company_name}}",
     "body": "Hi {{first_name}},\n\nImagine {{company_name}} being featured in articles on websites that your ideal customers already read. That's exactly what we help businesses achieve.\n\nWe write expert articles about topics in {{industry}} and place them on established publications. Each piece naturally highlights your brand and drives quality traffic back to {{website}}.\n\nNo templates, no shortcuts — every article is custom-written for your brand.\n\nWould you like to see some relevant site options?\n\nCheers,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on relevant publications",
     "body": "Hi {{first_name}},\n\nI'm reaching out because I think {{company_name}} would benefit from featured article placements on industry websites.\n\nHere's what we do at Uplyncio:\n— We find publications relevant to {{industry}}\n— We create an original, high-quality article featuring your brand\n— We get it published with a link back to {{website}}\n— You approve everything before it goes live\n\nIt's a hands-off way to build your brand's visibility and authority online.\n\nWant me to share a few options?\n\nRegards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{first_name}}, content idea for {{company_name}}",
     "body": "Hi {{first_name}},\n\nTraditional advertising is expensive and often ignored. But when your brand appears as a featured guest article on a trusted website, people pay attention.\n\nThat's what we do at Uplyncio. We help businesses like {{company_name}} get published on reputable websites in {{industry}} through professionally written guest content.\n\nThe articles read naturally, mention your brand in context, and link back to {{website}}. It builds trust in a way that ads simply can't.\n\nCurious to see how this could work for you?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest posting for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI wanted to share an approach that's working really well for businesses in {{industry}} right now — guest article placements on niche-relevant websites.\n\nInstead of competing for attention with ads, you get {{company_name}} featured in editorial content on websites that your target audience already reads and trusts.\n\nWe handle everything: research, writing, placement, and publishing. You just review and approve.\n\nWould it be worth exploring for {{company_name}}?\n\nThanks,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Publication placement for {{company_name}}",
     "body": "Hi {{first_name}},\n\nWhat if {{company_name}} was mentioned in articles on the most respected websites in {{industry}}?\n\nWe make that happen. Our team writes high-quality guest articles tailored to your brand and places them on established, relevant publications. Each article includes a natural reference to {{company_name}} and a link to {{website}}.\n\nIt's professional, effective, and completely hands-off for you.\n\nReady to see some options?\n\nBest regards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest article — {{company_name}}",
     "body": "Hi {{first_name}},\n\nI noticed {{company_name}} at {{website}} and wanted to suggest a strategy that could expand your online reach significantly.\n\nWe help brands get published on established websites through guest articles. These aren't random blog posts — they're strategic content placements on websites that your audience in {{industry}} actually reads.\n\nThe result is more visibility, stronger authority, and a steady stream of new visitors to your site.\n\nShall I put together a few relevant options?\n\nCheers,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on established industry websites",
     "body": "Hi {{first_name}},\n\nI'll get straight to the point. We help businesses in {{industry}} get featured on reputable websites through professionally written guest articles.\n\nFor {{company_name}}, this would mean:\n— Expert articles published on trusted industry sites\n— Your brand positioned as an authority in your space\n— Quality backlinks driving traffic to {{website}}\n— Zero effort required from your team\n\nWe've done this for hundreds of businesses. Want to see what's possible for yours?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    # 21-30: Curiosity + engagement
    {"subject": "Article idea for {{company_name}}",
     "body": "Hi {{first_name}},\n\nMany businesses in {{industry}} are discovering that getting featured on respected websites through guest articles is one of the most cost-effective ways to grow their brand online.\n\nHas {{company_name}} explored this approach? If not, I'd love to show you how it works.\n\nWe write expert content about your industry, place it on relevant publications, and include a natural mention of your brand. It builds credibility and drives targeted traffic to {{website}}.\n\nHappy to share some examples if you're curious.\n\nKind regards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{first_name}}, guest post for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI was researching businesses in {{industry}} and {{company_name}} caught my eye. I wanted to share something that I think could be genuinely valuable.\n\nWe help businesses get featured on well-known websites through guest article placements. It's not link building or SEO tricks — it's real, editorial-quality content published on trusted websites in your niche.\n\nEach placement is designed to showcase your expertise and drive relevant visitors to {{website}}.\n\nWould you be open to hearing more?\n\nThanks,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Publishing {{company_name}} on industry publications",
     "body": "Hi {{first_name}},\n\nI visited {{website}} and had an idea that I wanted to share.\n\nWhat if {{company_name}} was featured in expert articles on popular websites in {{industry}}? It's one of the most effective ways to build your brand's reputation online — and we can make it happen.\n\nWe write the content, find the right publications, and handle the publishing. You just say yes.\n\nInterested in seeing some site options?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest post — {{company_name}}",
     "body": "Hi {{first_name}},\n\nThere's a strategy that leading brands in {{industry}} are using to build authority online — and it's simpler than you might think.\n\nThey're getting featured on established industry websites through guest articles. These aren't ads — they're informative, well-written pieces that position the brand as a trusted voice in the space.\n\nI think {{company_name}} is perfectly positioned to benefit from this same approach. We'd handle everything from writing to publishing.\n\nCurious to learn more?\n\nBest regards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on {{industry}} websites?",
     "body": "Hi {{first_name}},\n\nI'll keep this short. We help businesses like {{company_name}} get published on reputable industry websites through guest content.\n\nIt's a straightforward process:\n1. We identify the best sites in {{industry}} for your brand\n2. We write a compelling article featuring {{company_name}}\n3. We get it published with a link to {{website}}\n4. You review everything before publication\n\nNo gimmicks, no spam — just quality content on quality websites.\n\nWant to see some options?\n\nCheers,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{first_name}}, editorial idea for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI was looking at {{company_name}} and thought of a simple way to accelerate your brand's growth online.\n\nGuest article placements on trusted industry websites can put {{company_name}} in front of thousands of potential customers in {{industry}} — people who are already interested in what you offer.\n\nWe write the articles, handle the placement, and ensure everything represents your brand well. It's a proven strategy that delivers real results.\n\nWant me to share a few relevant site options?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on industry publications",
     "body": "Hi {{first_name}},\n\nTrust is everything in business. And one of the best ways to build trust online is by being featured on websites that your audience already respects.\n\nWe help brands like {{company_name}} achieve exactly this through strategic guest article placements in {{industry}}. Every article is professionally written, genuinely valuable to readers, and naturally showcases your brand.\n\nThe best part? We handle the entire process for you.\n\nReady to explore this for {{company_name}}?\n\nRegards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest article idea — {{company_name}}",
     "body": "Hi {{first_name}},\n\n{{company_name}} clearly has deep expertise in {{industry}}. But is that expertise being seen by the right people?\n\nWe help businesses showcase their knowledge through guest articles on established industry websites. We craft compelling content that highlights your expertise, place it on relevant publications, and drive interested readers back to {{website}}.\n\nIt's a powerful way to establish thought leadership and attract new business.\n\nWould you like to learn more about how this works?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on relevant {{industry}} websites",
     "body": "Hi {{first_name}},\n\nWant to get {{company_name}} in front of a completely new audience? Here's how.\n\nWe write expert-level articles related to {{industry}} and place them on popular websites that your target customers read. Each article features your brand naturally and includes a link to {{website}}.\n\nIt's like being recommended by a trusted source — because that's essentially what it is.\n\nI'd love to show you some publication options. Interested?\n\nThanks,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Editorial content for {{company_name}}",
     "body": "Hi {{first_name}},\n\nThe {{industry}} space is competitive, and standing out matters. One proven way to differentiate {{company_name}} is through featured articles on the websites your audience trusts most.\n\nWe specialize in this — writing and placing guest content that positions your brand as a leader in your space. Every placement is strategic, high-quality, and designed to drive real results.\n\nCan I share some sites that would be a good fit for {{company_name}}?\n\nBest regards,\n{{sender_name}}\nUplyncio.com"},

    # 31-40: Social proof + results
    {"subject": "{{first_name}}, article placement for {{company_name}}",
     "body": "Hi {{first_name}},\n\nBusinesses in {{industry}} are seeing impressive results from guest article placements on established websites. More brand visibility, stronger credibility, and a steady flow of new visitors.\n\nI think {{company_name}} could achieve the same. We'd write high-quality articles featuring your brand and place them on relevant, trusted publications.\n\nThe process is completely managed — you approve, we deliver.\n\nWant to see some examples of what we've done recently?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest content for {{company_name}}",
     "body": "Hi {{first_name}},\n\nAt Uplyncio, we've helped businesses across {{industry}} get featured on hundreds of established websites. The feedback has been consistently positive — more visibility, more traffic, and stronger brand authority.\n\nI believe {{company_name}} would see similar results. We'd create custom content for your brand and place it on publications that matter in your space.\n\nEverything is handled for you — writing, outreach, and publishing.\n\nShall I prepare a few options?\n\nCheers,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on well-known industry websites",
     "body": "Hi {{first_name}},\n\nGuest content placement is one of the most reliable strategies for building brand authority online. Businesses in {{industry}} are using it to get featured on websites their customers already read and trust.\n\n{{company_name}} is well-positioned to benefit from this approach. We'd handle everything — identifying the right sites, creating compelling content, and managing the publishing process.\n\nWant to learn how this could work specifically for your brand?\n\nBest regards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Article placement idea — {{company_name}}",
     "body": "Hi {{first_name}},\n\nThere's a reason why leading brands in {{industry}} invest in guest content placement — it works. Being featured on established websites builds credibility, reaches new audiences, and drives quality traffic.\n\nWe help businesses like {{company_name}} tap into this strategy. We find the right publications, write expert content featuring your brand, and handle everything from start to finish.\n\nInterested in seeing what sites would work for {{company_name}}?\n\nThanks,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest post idea for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI noticed {{company_name}} at {{website}} and wanted to share an approach that's been delivering great results for businesses in {{industry}}.\n\nWe place guest articles on reputable industry websites — articles that feature your brand, showcase your expertise, and drive readers to your site. It's editorial-quality content, not advertorials or sponsored posts.\n\nWe manage the entire process. All you need to do is approve.\n\nReady to get started?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on industry websites",
     "body": "Hi {{first_name}},\n\nIn today's competitive {{industry}} landscape, getting noticed requires more than just having a great product or service. It requires visibility in the right places.\n\nThat's where we come in. We help brands like {{company_name}} get featured on trusted industry websites through guest articles. It's a cost-effective way to build authority and attract new customers.\n\nShall I share a few relevant opportunities?\n\nKind regards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{first_name}}, a guest post idea",
     "body": "Hi {{first_name}},\n\nAfter visiting {{website}}, I'm convinced that {{company_name}} deserves a wider audience. You've clearly built something valuable.\n\nWe help businesses like yours get the visibility they deserve through strategic guest article placements on industry websites. Professional content, real publications, genuine results.\n\nI'd love to help {{company_name}} reach more people. Can I show you how?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest article for {{company_name}}",
     "body": "Hi {{first_name}},\n\nWant to strengthen {{company_name}}'s position as a trusted name in {{industry}}? Guest article placements can help.\n\nWhen your brand is featured on respected industry websites, it sends a powerful signal to potential customers — that {{company_name}} is a credible, established player in the market.\n\nWe create and place these articles for you, making the entire process effortless.\n\nWould you like to explore this?\n\nRegards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Content idea for {{company_name}}",
     "body": "Hi {{first_name}},\n\nSmart businesses in {{industry}} know that visibility on the right platforms matters more than visibility everywhere. That's why they invest in guest content placements on respected, niche-relevant websites.\n\nWe'd love to help {{company_name}} do the same. We'll write compelling content that represents your brand well and get it published where it matters most.\n\nInterested in a few recommendations?\n\nCheers,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on relevant websites",
     "body": "Hi {{first_name}},\n\nI believe {{company_name}} has the potential to be even more visible in {{industry}}. And I have a specific idea about how to make that happen.\n\nGuest article placements on reputable industry websites can introduce your brand to thousands of new potential customers. We handle everything — the writing, the outreach, and the publishing.\n\nCan I share some site options that would be ideal for {{company_name}}?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    # 41-50: Direct + concise
    {"subject": "{{first_name}}, article idea for {{company_name}}",
     "body": "Hi {{first_name}},\n\nWe help businesses get featured on established industry websites through guest articles. I think {{company_name}} would be a great fit.\n\nWe write the content, find the right sites in {{industry}}, and handle publishing. You just approve.\n\nWant to see some options?\n\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest post placement for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI visited {{website}} and wanted to suggest something. We can get {{company_name}} featured on respected websites in {{industry}} through professionally written guest articles.\n\nEach article builds your brand's credibility and drives qualified traffic to your site. We manage everything.\n\nInterested in seeing what's available?\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{first_name}} — guest post for {{company_name}}",
     "body": "Hi {{first_name}},\n\nI'm {{sender_name}} from Uplyncio, a guest posting platform. We help businesses like {{company_name}} get published on quality websites in {{industry}}.\n\nOur clients use this to build brand authority, reach new audiences, and improve their online presence. We handle all the writing and publishing.\n\nWant to learn more?\n\nRegards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on {{industry}} publications",
     "body": "Hi {{first_name}},\n\nIs {{company_name}} looking to expand its online presence? We help businesses in {{industry}} get featured on reputable websites through guest content.\n\nIt's a simple, effective way to build credibility and reach new customers. We manage the entire process.\n\nHappy to share details if this sounds relevant.\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{first_name}}, publishing {{company_name}}",
     "body": "Hi {{first_name}},\n\nI'm reaching out because I believe {{company_name}} would benefit from being featured on established websites in {{industry}}.\n\nWe do this through guest articles — original, high-quality content that positions your brand as an authority. We handle everything from writing to publishing.\n\nCan I share a few site options?\n\nThanks,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest posting — {{company_name}}",
     "body": "Hi {{first_name}},\n\nHere's a simple idea for {{company_name}} — let's get your brand featured on trusted websites in {{industry}} through well-crafted guest articles.\n\nWe write the content, handle the placement, and you get the visibility. It's worked for hundreds of businesses and it can work for yours too.\n\nReady to explore this?\n\nCheers,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on relevant industry publications",
     "body": "Hi {{first_name}},\n\nI've been admiring {{company_name}}'s work in {{industry}} and wanted to suggest a collaboration.\n\nWe can get your brand featured on well-known industry publications through guest articles. It's a natural, effective way to build authority and attract new business.\n\nI'd love to discuss the possibilities. Open to it?\n\nBest regards,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest article for {{company_name}}",
     "body": "Hi {{first_name}},\n\nA quick suggestion for {{company_name}} — have you considered getting your brand published on respected websites in {{industry}}?\n\nWe make this happen through guest articles. Professional content, real sites, genuine results. We manage everything so you don't have to.\n\nLet me know if you'd like to see some options.\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "{{company_name}} on established websites",
     "body": "Hi {{first_name}},\n\nI'll take just a moment of your time. We help businesses like {{company_name}} get featured on established websites in {{industry}} through guest content.\n\nIf you're looking to build your brand's online presence and reach new customers, this is one of the most effective approaches available.\n\nWant to learn more? Just reply to this email.\n\nBest,\n{{sender_name}}\nUplyncio.com"},

    {"subject": "Guest post placement — {{company_name}}",
     "body": "Hi {{first_name}},\n\nI have one idea that I think could genuinely help {{company_name}} grow its online presence.\n\nGuest articles on respected industry websites. We write them, we place them, and your brand gets the visibility it deserves in {{industry}}. Simple, effective, and completely managed.\n\nShall I send over some site options?\n\nThanks,\n{{sender_name}}\nUplyncio.com"},
]


def get_template(index: int) -> dict:
    """Round-robin: returns template for email #index (0-based)."""
    return TEMPLATES[index % len(TEMPLATES)]


def render_template(template: dict, variables: dict) -> dict:
    """Replace {{variables}} in subject and body."""
    subject = template["subject"]
    body = template["body"]
    for key, val in variables.items():
        subject = subject.replace("{{" + key + "}}", str(val))
        body = body.replace("{{" + key + "}}", str(val))
    body_html = body.replace("\n", "<br>") + COMPANY_FOOTER
    return {"subject": subject, "body": body, "body_html": body_html}
