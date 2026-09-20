import pymysql

from config.settings import MYSQL_CONFIG
from musicbrainz import MusicBrainzClient
from musicbrainz.adapter import MusicBrainzDataAdapter
from musicbrainz.repository import ArtistRepository


def main():

    # 1. 创建 MusicBrainz Client
    client = MusicBrainzClient(
        user_agent="MusicMind/1.0 (your_email@example.com)"
    )

    # 2. 创建 Adapter
    adapter = MusicBrainzDataAdapter()


    # 3. 连接 MySQL
    connection = pymysql.connect(
        **MYSQL_CONFIG
    )


    try:

        print("=" * 60)
        print("开始搜索 Artist")
        print("=" * 60)


        # 4. 请求 MusicBrainz
        result = client.search_artist("周杰伦")


        print("返回类型：")
        print(type(result))


        print("\n返回字段：")
        print(result.keys())


        # 5. 获取 artists 列表
        artists = result["artists"]


        print("\n搜索结果数量：")
        print(len(artists))


        # 6. 选择第一个结果
        artist_data = artists[0]


        print("\nMusicBrainz Artist 原始数据：")
        print(artist_data)



        # 7. Adapter 转换
        artist = adapter.artist_to_musicmind(
            artist_data
        )


        print("\nMusicMind Artist：")
        print(artist)



        # 8. Repository 保存
        repository = ArtistRepository(
            connection
        )


        artist_id = repository.upsert(
            artist
        )


        print("\n插入数据库成功")
        print("数据库 Artist ID:")
        print(artist_id)



    finally:

        connection.close()



if __name__ == "__main__":
    main()