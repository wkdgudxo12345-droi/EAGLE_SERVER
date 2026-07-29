from eagle.jora_card_today100 import _JoraSearchCardParser


def test_jora_search_card_is_auditable() -> None:
    page = '''
    <div id="r_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" class="job-card result organic-job"
      data-braze-job-panel-view="{&quot;job_id&quot;:&quot;aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&quot;,&quot;job_title&quot;:&quot;Laundry Attendant&quot;,&quot;location&quot;:&quot;Darwin NT&quot;,&quot;company_name&quot;:&quot;Territory Laundry&quot;}">
      <h2 class="job-title"><a class="job-link" href="/job/Laundry-Attendant-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?x=1">Laundry Attendant</a></h2>
      <span class="job-company">Territory Laundry</span>
      <a class="job-location" href="/jobs-in-Darwin-NT">Darwin NT</a>
      <div class="job-abstract"><ul><li>Physically active laundry work with training provided.</li></ul></div>
      <span class="job-listed-date">Posted 2h ago</span>
    </div>
    '''
    parser = _JoraSearchCardParser()
    parser.feed(page)
    parser.close()
    assert len(parser.cards) == 1
    card = parser.cards[0]
    assert card["source_id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert card["title"] == "Laundry Attendant"
    assert card["company"] == "Territory Laundry"
    assert card["location"] == "Darwin NT"
    assert card["listed"] == "Posted 2h ago"
    assert card["url"] == "https://au.jora.com/job/Laundry-Attendant-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert "training provided" in card["description"]
