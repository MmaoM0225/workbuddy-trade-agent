#!/usr/bin/env python
# -*- coding: utf-8 -*-
import datetime
import json

ns = json.load(open("E:/cashfree/agent/test/data/daily_20261023/news.json", encoding="utf-8"))
for i, n in enumerate(ns, 1):
    t = datetime.datetime.fromtimestamp(n["publish_time"]).strftime("%m-%d %H:%M")
    labels = ",".join(n["labels"]) or "-"
    print("%2d. %s [%s] %s" % (i, t, labels, n["title"][:40]))
