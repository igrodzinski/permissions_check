import json
import os
import plotly.graph_objects as go

# Wczytaj dane
with open('sankey_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

nodes = data.get('nodes', [])
links = data.get('links', [])

TYPE_COLORS = {
    'model':     'rgba(231,76,60,0.9)',
    'explore':   'rgba(230,126,34,0.9)',
    'dashboard': 'rgba(52,152,219,0.9)',
    'group':     'rgba(155,89,182,0.9)',
    'role':      'rgba(26,188,156,0.9)',
    'user':      'rgba(52,73,94,0.9)',
}
node_base_colors = [TYPE_COLORS.get(n.get('type'), 'rgba(150,150,150,0.85)') for n in nodes]
link_base_colors = ['rgba(255,200,0,0.45)'] * len(links)

fig = go.Figure(go.Sankey(
    arrangement='snap',
    node=dict(
        pad=20, thickness=28,
        line=dict(color='white', width=0.5),
        label=[n.get('label','') for n in nodes],
        color=node_base_colors,
        customdata=list(range(len(nodes))),
    ),
    link=dict(
        source=[l['source'] for l in links],
        target=[l['target'] for l in links],
        value=[l.get('value',1) for l in links],
        color=link_base_colors,
        customdata=list(range(len(links))),
    )
))

fig.update_layout(
    title_text='Przepływ Uprawnień: Model → Explore → Dashboard → Encja',
    font=dict(size=12, family='Inter, Arial, sans-serif', color='white'),
    height=820, paper_bgcolor='#1a1a2e',
    margin=dict(l=20, r=20, t=60, b=20)
)

html_body = fig.to_html(include_plotlyjs='cdn', full_html=True)

hover_js = """
<script>
(function() {
  var linksData     = LINKS_JSON;
  var baseNodeColors = NODE_COLORS_JSON;
  var baseLinkColors = LINK_COLORS_JSON;

  var BG = '#1a1a2e';

  function hexToRgba(color, alpha) {
    return color; // już jest rgba
  }

  function dimColor(color, alpha) {
    // zamień kolor na bardzo przezroczysty w kolorze tła
    return 'rgba(26,26,46,' + alpha + ')';
  }

  var poll = setInterval(function() {
    var gd = document.querySelector('.js-plotly-plot');
    if (!gd || !gd._fullData || !gd._fullData.length) return;
    clearInterval(poll);

    gd.on('plotly_hover', function(eventData) {
      if (!eventData || !eventData.points || !eventData.points.length) return;
      var pt = eventData.points[0];

      // W Plotly Sankey: węzły mają 'label', linki - 'source', 'target'
      var isNode = (pt.label !== undefined && pt.source === undefined);
      var idx = pt.pointNumber;
      if (idx === undefined || idx === null) return;

      var connLinks = new Set();
      var connNodes = new Set();

      if (isNode) {
        connNodes.add(idx);
        linksData.forEach(function(l, i) {
          if (l.source === idx || l.target === idx) {
            connLinks.add(i);
            connNodes.add(l.source);
            connNodes.add(l.target);
          }
        });
      } else {
        // Hover na link - pointNumber to indeks linku
        connLinks.add(idx);
        var l = linksData[idx];
        if (l) {
          connNodes.add(l.source);
          connNodes.add(l.target);
        }
      }

      // Tworzymy nowe kolory przez Plotly.restyle
      // Kluczowe: restyle nie triggeruje unhover dla Sankey!
      var newNodeColors = baseNodeColors.map(function(c, i) {
        return connNodes.has(i) ? c : 'rgba(26,26,46,0.07)';
      });
      var newLinkColors = baseLinkColors.map(function(c, i) {
        return connLinks.has(i) ? 'rgba(255,200,0,0.85)' : 'rgba(26,26,46,0.04)';
      });

      Plotly.restyle(gd, {
        'node.color': [newNodeColors],
        'link.color': [newLinkColors]
      }, [0]);
    });

    gd.on('plotly_unhover', function(eventData) {
      Plotly.restyle(gd, {
        'node.color': [baseNodeColors],
        'link.color': [baseLinkColors]
      }, [0]);
    });

  }, 200);
})();
</script>
""".replace('LINKS_JSON', json.dumps(links)) \
   .replace('NODE_COLORS_JSON', json.dumps(node_base_colors)) \
   .replace('LINK_COLORS_JSON', json.dumps(link_base_colors))

html_body = html_body.replace('</body>', hover_js + '</body>')

out_path = os.path.join(os.getcwd(), 'sankey_chart.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html_body)

print(f"✅ Zapisano: {out_path}")
print("💡 Otwórz sankey_chart.html w przeglądarce lub IFrame w Jupyter")
