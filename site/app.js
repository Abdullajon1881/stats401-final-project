/* ==========================================================================
   Tashkent Transit & Walkability — interim prototype (Week 5)

   Two linked views over one shared state:
     * a geographic access map (D3 geoMercator + SVG)
     * a ranked dot plot of modelled metro access by district

   Every number shown comes from site/data/*.json, which scripts/build_web_data.py
   copies from the audited Week 4 analysis. Nothing analytical is computed here,
   and no city metric is hard-coded in this file.
   ========================================================================== */

(function () {
  "use strict";

  // ── configuration ──────────────────────────────────────────────────────
  var DATA = "data/";
  var FILES = {
    city: DATA + "city_summary.json",
    districts: DATA + "districts.geojson",
    isochrone: DATA + "metro_isochrone_10min.geojson",
    access: DATA + "metro_access_points.geojson",
    stations: DATA + "metro_stations.geojson",
    bus: DATA + "bus_stops.geojson",
    bazaars: DATA + "bazaars.geojson",
    density: DATA + "population_density.geojson"
  };

  // A district reporting no metro access at all gets a cautionary note when
  // its nearest cell sits this close to the budget: at that range the result
  // turns on mapping and walking assumptions rather than on geography.
  var TIGHT_MARGIN_M = 100;

  // Deliberately light: population is context, and the metro access shading
  // drawn on top of it has to stay readable.
  var DENSITY_RAMP = ["#f4f2ed", "#ddece7", "#bcdad3", "#95c3bb", "#6ca7a0", "#48857f"];

  // ── shared state ───────────────────────────────────────────────────────
  var state = {
    selectedDistrict: null,
    hoveredDistrict: null,
    layers: {
      density: true,
      isochrone: true,
      access: true,
      stations: false,
      bus: false,
      bazaars: false
    }
  };

  var data = {};
  var byDistrict = new Map();
  var ranked = [];
  var densityColor = null;

  // ── formatting ─────────────────────────────────────────────────────────
  var fmtPeople = d3.format(",.0f");
  var fmtPct1 = d3.format(".1f");
  var fmtDensity = d3.format(",.0f");
  var fmtMetres = d3.format(",.1f");

  function pct(value) { return fmtPct1(value) + "%"; }
  function people(value) { return fmtPeople(value); }
  function density(value) { return fmtDensity(value) + " /km²"; }

  // ── boot ───────────────────────────────────────────────────────────────
  function fail(message) {
    var box = document.getElementById("load-error");
    document.getElementById("load-error-detail").textContent = message;
    box.hidden = false;
    document.getElementById("app").hidden = true;
  }

  function loadJson(url) {
    return d3.json(url).then(function (value) {
      if (!value) throw new Error("empty response from " + url);
      return value;
    }, function (error) {
      throw new Error("could not load " + url + " (" + (error && error.message ? error.message : error) + ")");
    });
  }

  Promise.all([
    loadJson(FILES.city), loadJson(FILES.districts), loadJson(FILES.isochrone),
    loadJson(FILES.access), loadJson(FILES.stations), loadJson(FILES.bus),
    loadJson(FILES.bazaars), loadJson(FILES.density)
  ]).then(function (loaded) {
    data.city = loaded[0];
    data.districts = loaded[1];
    data.isochrone = loaded[2];
    data.access = loaded[3];
    data.stations = loaded[4];
    data.bus = loaded[5];
    data.bazaars = loaded[6];
    data.density = loaded[7];
    start();
  }).catch(function (error) {
    fail(error && error.message ? error.message : String(error));
  });

  // ── start ──────────────────────────────────────────────────────────────
  function start() {
    document.getElementById("app").hidden = false;

    data.districts.features.forEach(function (f) {
      byDistrict.set(f.properties.district_name, f);
    });
    ranked = data.districts.features.slice().sort(function (a, b) {
      return d3.descending(a.properties.metro_access_pct, b.properties.metro_access_pct) ||
             d3.ascending(a.properties.district_name, b.properties.district_name);
    });

    var values = data.density.features.map(function (f) { return f.properties.density_per_km2; });
    var upper = d3.quantile(values.slice().sort(d3.ascending), 0.98) || d3.max(values);
    densityColor = d3.scaleSequentialSqrt(d3.interpolateRgbBasis(DENSITY_RAMP))
      .domain([0, upper]).clamp(true);

    bindCitySummary();
    buildDensityLegend(upper);
    wireLayerButtons();
    wireReset();

    renderMap();
    renderDotPlot();
    renderDistrictDetails();

    observeResize();
  }

  // ── headline figures, read from JSON ───────────────────────────────────
  function bindCitySummary() {
    var c = data.city;
    var bindings = {
      metro_pct: pct(c.metro_access_pct),
      bus_only_pct: pct(c.bus_only_pct),
      underserved_pct: pct(c.underserved_pct),
      metro_people: people(c.metro_access_population),
      bus_only_people: people(c.bus_only_population),
      underserved_people: people(c.underserved_population),
      analysis_population: people(c.analysis_population),
      walk_minutes: c.walking_time_minutes + "-minute",
      walk_speed: c.walking_speed_kmh + " km/h",
      budget: fmtPeople(c.distance_budget_m) + " m",
      reference_period: c.reference_period,
      analysis_version: c.analysis_version,
      snapping_method: c.snapping_method
    };
    Object.keys(bindings).forEach(function (key) {
      d3.selectAll('[data-bind="' + key + '"]').text(bindings[key]);
    });
  }

  function buildDensityLegend(upper) {
    var ramp = d3.select("#density-ramp");
    ramp.selectAll("span").data(d3.range(24)).join("span")
      .style("background", function (i) { return densityColor(upper * (i + 0.5) / 24); });
    d3.select("#density-scale").selectAll("span")
      .data([0, upper]).join("span")
      .text(function (d, i) { return (i === 1 ? fmtDensity(d) + "+" : fmtDensity(d)); });
  }

  // ── tooltip ────────────────────────────────────────────────────────────
  var tooltipEl = document.getElementById("tooltip");

  function showTooltip(html, event) {
    tooltipEl.innerHTML = html;
    tooltipEl.classList.add("is-visible");
    tooltipEl.setAttribute("aria-hidden", "false");
    moveTooltip(event);
  }

  function moveTooltip(event) {
    if (!tooltipEl.classList.contains("is-visible")) return;
    var pad = 14;
    var rect = tooltipEl.getBoundingClientRect();
    var x = event.clientX + pad;
    var y = event.clientY + pad;
    if (x + rect.width > window.innerWidth - 8) x = event.clientX - rect.width - pad;
    if (y + rect.height > window.innerHeight - 8) y = event.clientY - rect.height - pad;
    tooltipEl.style.left = Math.max(8, x) + "px";
    tooltipEl.style.top = Math.max(8, y) + "px";
  }

  function hideTooltip() {
    tooltipEl.classList.remove("is-visible");
    tooltipEl.setAttribute("aria-hidden", "true");
  }

  function row(key, value, cls) {
    return '<span class="tt-row"><span class="k">' + key + '</span>' +
           '<span class="v' + (cls ? " " + cls : "") + '">' + value + "</span></span>";
  }

  function districtTooltip(p) {
    return '<span class="tt-name">' + p.label + "</span>" +
      row("Population", people(p.official_population)) +
      row("Metro access", pct(p.metro_access_pct)) +
      row("Bus-only", pct(p.bus_only_pct)) +
      row("Underserved", pct(p.underserved_pct)) +
      row("Density", density(p.population_density_per_km2)) +
      row("Metro points", p.metro_access_points_in_district) +
      '<span class="tt-foot">Click to pin this district.</span>';
  }

  // ── selection / hover ──────────────────────────────────────────────────
  function setHovered(name) {
    if (state.hoveredDistrict === name) return;
    state.hoveredDistrict = name;
    updateSelection();
  }

  function toggleSelected(name) {
    state.selectedDistrict = state.selectedDistrict === name ? null : name;
    updateSelection();
    renderDistrictDetails();
    announce();
  }

  function clearSelection() {
    state.selectedDistrict = null;
    updateSelection();
    renderDistrictDetails();
    announce();
  }

  function announce() {
    var live = document.getElementById("live-region");
    var name = state.selectedDistrict;
    if (!name) { live.textContent = "District selection cleared."; return; }
    var p = byDistrict.get(name).properties;
    live.textContent = p.label + " selected. Metro access " + pct(p.metro_access_pct) +
      ", bus-only " + pct(p.bus_only_pct) + ", underserved " + pct(p.underserved_pct) + ".";
  }

  function updateSelection() {
    var selected = state.selectedDistrict;
    var hovered = state.hoveredDistrict;

    d3.selectAll(".district-shape")
      .classed("is-selected", function (d) { return d.properties.district_name === selected; })
      .classed("is-hovered", function (d) {
        return d.properties.district_name === hovered && d.properties.district_name !== selected;
      })
      .attr("aria-pressed", function (d) { return d.properties.district_name === selected; });

    d3.selectAll(".district-shape").filter(function (d) {
      return d.properties.district_name === selected || d.properties.district_name === hovered;
    }).raise();

    var halo = d3.select("#selection-halo");
    if (selected && halo.size()) {
      halo.attr("d", mapPath(byDistrict.get(selected))).attr("display", null);
    } else if (halo.size()) {
      halo.attr("display", "none");
    }

    d3.selectAll(".dot-row")
      .classed("is-selected", function (d) { return d.properties.district_name === selected; })
      .classed("is-hovered", function (d) {
        return d.properties.district_name === hovered && d.properties.district_name !== selected;
      });
    d3.selectAll(".dot-row").select(".dot-mark")
      .attr("r", function (d) { return d.properties.district_name === selected ? 7 : 5; });
    d3.selectAll(".dot-row-hit")
      .attr("aria-pressed", function (d) { return d.properties.district_name === selected; });

    d3.select("#reset-selection").attr("hidden", selected ? null : "hidden");

    // Bus stops dim outside a pinned district, so the pin reads on that layer too.
    d3.selectAll(".bus-dot").attr("fill-opacity", function (d) {
      if (!selected) return 0.55;
      return d.properties.district_name === selected ? 0.85 : 0.14;
    });
  }

  // ── map ────────────────────────────────────────────────────────────────
  var projection = d3.geoMercator();
  var geoPath = d3.geoPath(projection);
  function mapPath(feature) { return geoPath(feature); }

  function mapSize() {
    var el = document.getElementById("map");
    var width = Math.max(280, Math.floor(el.clientWidth));
    var ratio = width >= 700 ? 0.72 : 0.95;
    var height = Math.min(640, Math.max(320, Math.round(width * ratio)));
    return { width: width, height: height };
  }

  function renderMap() {
    var size = mapSize();
    var pad = 10;
    projection.fitExtent(
      [[pad, pad], [size.width - pad, size.height - pad]], data.districts
    );

    var host = d3.select("#map");
    host.selectAll("svg").remove();

    var svg = host.append("svg")
      .attr("viewBox", "0 0 " + size.width + " " + size.height)
      .attr("width", size.width)
      .attr("height", size.height)
      .attr("role", "img")
      .attr("aria-label",
        "Map of Tashkent showing modelled ten-minute walking access to the metro, " +
        "population density, and the 12 analysis districts.");

    // background click clears a pinned district
    svg.append("rect")
      .attr("width", size.width).attr("height", size.height)
      .attr("fill", "transparent")
      .on("click", clearSelection);

    var gDensity = svg.append("g").attr("class", "layer-density");
    var gIso = svg.append("g").attr("class", "layer-isochrone");
    var gBus = svg.append("g").attr("class", "layer-bus");
    var gBazaar = svg.append("g").attr("class", "layer-bazaars");
    svg.append("path").attr("id", "selection-halo").attr("class", "district-halo").attr("display", "none");
    var gDistricts = svg.append("g").attr("class", "layer-districts");
    var gStations = svg.append("g").attr("class", "layer-stations");
    var gAccess = svg.append("g").attr("class", "layer-access");

    // population density (display only)
    gDensity.selectAll("path").data(data.density.features).join("path")
      .attr("class", "density-cell")
      .attr("d", geoPath)
      .attr("fill", function (d) { return densityColor(d.properties.density_per_km2); })
      .attr("fill-opacity", 0.62);

    // metro service area (display only)
    gIso.selectAll("path").data(data.isochrone.features).join("path")
      .attr("class", "iso-shape")
      .attr("d", geoPath);

    // bus stops — coverage, not individually interrogated
    gBus.selectAll("circle").data(data.bus.features).join("circle")
      .attr("class", "bus-dot")
      .attr("cx", function (d) { return projection(d.geometry.coordinates)[0]; })
      .attr("cy", function (d) { return projection(d.geometry.coordinates)[1]; })
      .attr("r", 1.5);

    gBazaar.selectAll("rect").data(data.bazaars.features).join("rect")
      .attr("class", "bazaar-mark")
      .attr("x", function (d) { return projection(d.geometry.coordinates)[0] - 2.4; })
      .attr("y", function (d) { return projection(d.geometry.coordinates)[1] - 2.4; })
      .attr("width", 4.8).attr("height", 4.8)
      .attr("transform", function (d) {
        var p = projection(d.geometry.coordinates);
        return "rotate(45 " + p[0] + " " + p[1] + ")";
      });

    // districts — the interactive layer
    gDistricts.selectAll("path").data(data.districts.features).join("path")
      .attr("class", "district-shape")
      .attr("d", geoPath)
      .attr("role", "button")
      .attr("tabindex", 0)
      .attr("aria-pressed", false)
      .attr("aria-label", function (d) {
        var p = d.properties;
        return p.label + " district. Metro access " + pct(p.metro_access_pct) +
          ", bus-only " + pct(p.bus_only_pct) + ", underserved " + pct(p.underserved_pct) +
          ". Activate to pin this district.";
      })
      .on("mouseenter", function (event, d) {
        setHovered(d.properties.district_name);
        showTooltip(districtTooltip(d.properties), event);
      })
      .on("mousemove", moveTooltip)
      .on("mouseleave", function () { setHovered(null); hideTooltip(); })
      .on("focus", function (event, d) { setHovered(d.properties.district_name); })
      .on("blur", function () { setHovered(null); })
      .on("click", function (event, d) {
        event.stopPropagation();
        toggleSelected(d.properties.district_name);
      })
      .on("keydown", function (event, d) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggleSelected(d.properties.district_name);
        } else if (event.key === "Escape") {
          clearSelection();
        }
      });

    // station centres (off by default; the access points carry the analysis)
    gStations.selectAll("circle").data(data.stations.features).join("circle")
      .attr("class", "station-mark")
      .attr("cx", function (d) { return projection(d.geometry.coordinates)[0]; })
      .attr("cy", function (d) { return projection(d.geometry.coordinates)[1]; })
      .attr("r", 4)
      .on("mouseenter", function (event, d) {
        showTooltip('<span class="tt-name">' + (d.properties.name_en || d.properties.name || "Metro station") +
          '</span><span class="tt-foot">Metro station centre — ' +
          (d.properties.district_name || "") + "</span>", event);
      })
      .on("mousemove", moveTooltip)
      .on("mouseleave", hideTooltip);

    // metro access points: entrances are filled circles, fallbacks hollow —
    // shape as well as fill, so the distinction survives without colour
    var access = gAccess.selectAll("circle").data(data.access.features).join("circle")
      .attr("class", function (d) {
        return d.properties.access_type === "station_fallback" ? "access-fallback" : "access-entrance";
      })
      .attr("cx", function (d) { return projection(d.geometry.coordinates)[0]; })
      .attr("cy", function (d) { return projection(d.geometry.coordinates)[1]; })
      .attr("r", function (d) {
        return d.properties.access_type === "station_fallback" ? 4.5 : 2.8;
      });

    access
      .on("mouseenter", function (event, d) {
        var p = d.properties;
        showTooltip('<span class="tt-name">' + (p.name || "Metro access point") + "</span>" +
          row("Type", p.kind_label) +
          '<span class="tt-foot">' + p.detail + "</span>", event);
      })
      .on("mousemove", moveTooltip)
      .on("mouseleave", hideTooltip);

    updateLayerVisibility();
    updateSelection();
  }

  // ── dot plot ───────────────────────────────────────────────────────────
  function renderDotPlot() {
    var host = d3.select("#dotplot");
    var width = Math.max(300, Math.floor(document.getElementById("dotplot").clientWidth));
    var narrow = width < 560;
    var rowHeight = narrow ? 28 : 33;
    var height = 0;

    host.selectAll("svg").remove();
    var svg = host.append("svg")
      .attr("role", "img")
      .attr("aria-label", "Districts ranked by modelled share of population within a " +
        "ten-minute walk of metro access, highest first.");

    // Measure the real rendered label widths rather than guessing a gutter:
    // "Shaykhantakhur" is clipped at phone width by any fixed estimate, and the
    // font that actually loads varies by platform.
    var probe = svg.append("g").attr("visibility", "hidden");
    var labelWidth = d3.max(ranked, function (d) {
      var node = probe.append("text").attr("class", "dot-label")
        .text(d.properties.label).node();
      return node.getComputedTextLength();
    }) || 90;
    probe.remove();

    var margin = {
      top: 30,
      right: narrow ? 46 : 58,
      bottom: 22,
      left: Math.min(Math.round(width * 0.46), Math.ceil(labelWidth) + 20)
    };
    var innerWidth = Math.max(80, width - margin.left - margin.right);
    height = margin.top + ranked.length * rowHeight + margin.bottom;

    svg.attr("viewBox", "0 0 " + width + " " + height)
      .attr("width", width).attr("height", height);

    var maxValue = d3.max(ranked, function (d) { return d.properties.metro_access_pct; });
    var x = d3.scaleLinear().domain([0, Math.max(5, maxValue * 1.12)]).range([0, innerWidth]).nice();

    var plot = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");

    // axis
    var ticks = x.ticks(narrow ? 4 : 6);
    var axis = plot.append("g").attr("class", "axis");
    axis.selectAll("line.axis-tick").data(ticks).join("line")
      .attr("class", "axis-tick")
      .attr("x1", x).attr("x2", x)
      .attr("y1", -8).attr("y2", ranked.length * rowHeight - rowHeight / 2);
    axis.selectAll("text").data(ticks).join("text")
      .attr("class", "axis-text")
      .attr("x", x).attr("y", -14)
      .attr("text-anchor", "middle")
      .text(function (d) { return d + "%"; });
    axis.append("line")
      .attr("class", "axis-line")
      .attr("x1", 0).attr("x2", 0)
      .attr("y1", -8).attr("y2", ranked.length * rowHeight - rowHeight / 2);

    var rows = plot.selectAll("g.dot-row").data(ranked, function (d) {
      return d.properties.district_name;
    }).join("g")
      .attr("class", "dot-row")
      .attr("transform", function (d, i) { return "translate(0," + (i * rowHeight) + ")"; });

    rows.append("line")
      .attr("class", "dot-leader")
      .attr("x1", 0).attr("y1", 0)
      .attr("x2", function (d) { return x(d.properties.metro_access_pct); })
      .attr("y2", 0);

    rows.append("text")
      .attr("class", "dot-label")
      .attr("x", -12).attr("y", 0)
      .attr("text-anchor", "end")
      .text(function (d) { return d.properties.label; });

    rows.append("circle")
      .attr("class", "dot-mark")
      .attr("cx", function (d) { return x(d.properties.metro_access_pct); })
      .attr("cy", 0)
      .attr("r", 5);

    rows.append("text")
      .attr("class", "dot-value")
      .attr("x", function (d) { return x(d.properties.metro_access_pct) + 11; })
      .attr("y", 0)
      .text(function (d) { return pct(d.properties.metro_access_pct); });

    // one transparent hit target per row: whole-row hover and keyboard focus
    rows.append("rect")
      .attr("class", "dot-row-hit")
      .attr("x", -margin.left).attr("y", -rowHeight / 2)
      .attr("width", width).attr("height", rowHeight)
      .attr("role", "button")
      .attr("tabindex", 0)
      .attr("aria-pressed", false)
      .attr("aria-label", function (d) {
        return d.properties.label + " district, metro access " +
          pct(d.properties.metro_access_pct) + ". Activate to pin this district.";
      })
      .on("mouseenter", function (event, d) {
        setHovered(d.properties.district_name);
        showTooltip(districtTooltip(d.properties), event);
      })
      .on("mousemove", moveTooltip)
      .on("mouseleave", function () { setHovered(null); hideTooltip(); })
      .on("focus", function (event, d) { setHovered(d.properties.district_name); })
      .on("blur", function () { setHovered(null); })
      .on("click", function (event, d) { toggleSelected(d.properties.district_name); })
      .on("keydown", function (event, d) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggleSelected(d.properties.district_name);
        } else if (event.key === "Escape") {
          clearSelection();
        }
      });

    updateSelection();
  }

  // ── district detail panel ──────────────────────────────────────────────
  function renderDistrictDetails() {
    var body = d3.select("#detail-body");
    var name = state.selectedDistrict;

    if (!name) {
      body.html('<p class="detail-empty">Select a district on the map or in the ranking ' +
        "below to see its figures here.</p>");
      return;
    }

    var p = byDistrict.get(name).properties;
    var total = p.metro_access_pct + p.bus_only_pct + p.underserved_pct;
    var html = "";

    html += '<p class="detail-name">' + p.label + "</p>";
    html += '<p class="detail-sub">' + people(p.official_population) + " residents · " +
      fmtDensity(p.area_km2) + " km²</p>";

    html += '<div class="split" role="img" aria-label="Access composition: metro ' +
      pct(p.metro_access_pct) + ", bus-only " + pct(p.bus_only_pct) +
      ", underserved " + pct(p.underserved_pct) + '">' +
      '<i class="s-metro" style="width:' + (p.metro_access_pct / total * 100) + '%"></i>' +
      '<i class="s-bus" style="width:' + (p.bus_only_pct / total * 100) + '%"></i>' +
      '<i class="s-under" style="width:' + (p.underserved_pct / total * 100) + '%"></i>' +
      "</div>";

    html += '<ul class="detail-list">';
    html += item("Metro access", pct(p.metro_access_pct) + " · " + people(p.metro_access_population), "v-metro");
    html += item("Bus-only", pct(p.bus_only_pct) + " · " + people(p.bus_only_population), "v-bus");
    html += item("Underserved", pct(p.underserved_pct) + " · " + people(p.underserved_population), "v-under");
    html += item("Population density", density(p.population_density_per_km2));
    html += item("Metro stations", p.metro_stations_in_district);
    html += item("Metro access points", p.metro_access_points_in_district);
    html += item("Bus stops", p.bus_stops_in_district);
    html += item("Bazaars", p.bazaars_in_district);
    html += "</ul>";

    var note = zeroAccessNote(p);
    if (note) html += '<p class="detail-caveat">' + note + "</p>";

    body.html(html);
  }

  function item(key, value, cls) {
    return '<li><span class="k">' + key + '</span><span class="v' +
      (cls ? " " + cls : "") + '">' + value + "</span></li>";
  }

  /* A district can only report zero metro access because no analysed cell fell
     inside the budget. When the nearest one missed by a very small margin that
     is a knife-edge result, not a robust finding, and the panel says so. Both
     the rule and the wording come from the district's own audited numbers, so
     no district is singled out in code. */
  function zeroAccessNote(p) {
    if (p.metro_access_pct > 0) return null;
    var margin = p.min_cell_metro_margin_m;
    var budget = data.city.distance_budget_m;
    var base = "No analysed population cell falls within the " + fmtPeople(budget) +
      " m metro budget. The nearest is " + fmtMetres(p.min_cell_metro_distance_m) + " m";
    if (margin <= TIGHT_MARGIN_M) {
      return base + " — only about " + fmtPeople(margin) +
        " m outside the threshold, so this result is sensitive to mapping and walking " +
        "assumptions.";
    }
    return base + ", " + fmtPeople(margin) + " m beyond the threshold.";
  }

  // ── layer controls ─────────────────────────────────────────────────────
  var LAYER_SELECTOR = {
    density: ".layer-density",
    isochrone: ".layer-isochrone",
    access: ".layer-access",
    stations: ".layer-stations",
    bus: ".layer-bus",
    bazaars: ".layer-bazaars"
  };

  function updateLayerVisibility() {
    Object.keys(LAYER_SELECTOR).forEach(function (key) {
      d3.select(LAYER_SELECTOR[key]).attr("display", state.layers[key] ? null : "none");
    });
    d3.select("#density-legend").style("opacity", state.layers.density ? 1 : 0.35);
  }

  function wireLayerButtons() {
    d3.selectAll(".chip").each(function () {
      var button = d3.select(this);
      var key = button.attr("data-layer");
      button.attr("aria-pressed", String(!!state.layers[key]));
      button.on("click", function () {
        state.layers[key] = !state.layers[key];
        button.attr("aria-pressed", String(state.layers[key]));
        updateLayerVisibility();
      });
    });
  }

  function wireReset() {
    d3.select("#reset-selection").on("click", clearSelection);
    d3.select("body").on("keydown", function (event) {
      if (event.key === "Escape" && state.selectedDistrict) clearSelection();
    });
  }

  // ── responsive re-render ───────────────────────────────────────────────
  function observeResize() {
    var lastMap = 0;
    var lastDot = 0;
    var pending = null;

    function refresh() {
      var mapWidth = document.getElementById("map").clientWidth;
      var dotWidth = document.getElementById("dotplot").clientWidth;
      if (Math.abs(mapWidth - lastMap) > 1) { lastMap = mapWidth; renderMap(); }
      if (Math.abs(dotWidth - lastDot) > 1) { lastDot = dotWidth; renderDotPlot(); }
    }

    function schedule() {
      if (pending) window.clearTimeout(pending);
      pending = window.setTimeout(function () { pending = null; refresh(); }, 120);
    }

    lastMap = document.getElementById("map").clientWidth;
    lastDot = document.getElementById("dotplot").clientWidth;

    if (typeof ResizeObserver === "function") {
      var observer = new ResizeObserver(schedule);
      observer.observe(document.getElementById("map"));
      observer.observe(document.getElementById("dotplot"));
    } else {
      window.addEventListener("resize", schedule);
    }
  }
})();
