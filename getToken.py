import os
import tushare as ts
pro = ts.pro_api('sZHJPUusHbElIatlxYMLLjqojtOAVPJXliwFMptiFahnypBaraHvsOEiqWQHqhDU')
pro._DataApi__http_url = "http://118.89.66.41:8010/"
df = pro.index_basic(limit=5)
print(df)
