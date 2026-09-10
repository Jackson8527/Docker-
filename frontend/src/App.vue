<template>
  <el-container class="layout">
    <el-aside width="200px">
      <div class="logo">🐳 Docker Manager</div>
      <el-menu router :default-active="$route.path" class="menu">
        <el-menu-item index="/containers">
          <el-icon><Box /></el-icon><span>容器</span>
        </el-menu-item>
        <el-menu-item index="/images">
          <el-icon><Picture /></el-icon><span>镜像</span>
        </el-menu-item>
        <el-menu-item index="/networks">
          <el-icon><Connection /></el-icon><span>网络</span>
        </el-menu-item>
        <el-menu-item index="/volumes">
          <el-icon><Coin /></el-icon><span>卷</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header>
        <h2>Docker 管理平台</h2>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style>
.layout { height: 100vh; }
.logo { padding: 16px; font-weight: bold; font-size: 16px; }
.menu { border-right: none; }
.el-header { display: flex; align-items: center; border-bottom: 1px solid #eee; }
</style>